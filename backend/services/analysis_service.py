from __future__ import annotations

import json
import logging
import calendar
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ai.context_builder import format_user_profile
from ai.providers import get_provider
from ai.usage_tracker import track_usage_from_result
from config import settings as app_settings
from db.database import SessionLocal
from db.models import (
    AnalysisProposal,
    AnalysisRun,
    DailyChecklistItem,
    ExerciseLog,
    FastingLog,
    FoodLog,
    HealthOptimizationFramework,
    HydrationLog,
    Message,
    SleepLog,
    SupplementLog,
    User,
    VitalsLog,
)
from services.health_framework_service import (
    active_frameworks_for_context,
    delete_framework,
    normalize_framework_name,
    update_framework,
    upsert_framework,
)
from utils.datetime_utils import end_of_day, start_of_day, today_for_tz, sleep_log_overlaps_window
from utils.encryption import decrypt_api_key
from utils.med_utils import parse_structured_list

logger = logging.getLogger(__name__)

VALID_RUN_TYPES = {"daily", "weekly", "monthly"}
PROPOSAL_KINDS = {"guidance_update", "prompt_adjustment", "experiment"}
PROPOSAL_STATUSES = {"pending", "approved", "rejected", "applied", "expired"}
PROPOSAL_TITLE_STOPWORDS = {
    "and",
    "for",
    "the",
    "with",
    "from",
    "into",
    "your",
    "this",
    "that",
    "user",
    "daily",
    "today",
    "toward",
    "towards",
    "improve",
    "improvement",
    "enhance",
    "enhancement",
}

UTILITY_SIGNAL_PROMPT = """Extract short longitudinal signal annotations from these notes.
Return JSON only:
{
  "energy_signals": ["short statements"],
  "stress_signals": ["short statements"],
  "symptom_signals": ["short statements"],
  "adherence_signals": ["short statements"],
  "confidence": 0.0
}
Rules:
- Use only provided notes.
- Keep each statement <= 20 words.
- If nothing is relevant, return empty arrays and low confidence."""

REASONING_SYNTHESIS_PROMPT = """You are a longitudinal health analytics assistant.
Analyze the supplied user metrics and produce adaptation proposals.

Return JSON only:
{
  "confidence": 0.0,
  "summary_markdown": "markdown summary",
  "risk_flags": [
    {"code": "short_code", "severity": "low|medium|high", "title": "title", "detail": "detail"}
  ],
  "recommendations": [
    {"title": "title", "detail": "detail", "priority": "low|medium|high", "requires_user_confirmation": true}
  ],
  "proposals": [
    {
      "proposal_kind": "guidance_update|experiment|prompt_adjustment",
      "title": "title",
      "rationale": "why",
      "confidence": 0.0,
      "payload": {"target": "domain|framework", "changes": ["concrete change"]},
      "diff_markdown": "optional prompt diff markdown"
    }
  ]
}
Rules:
- Never claim certainty beyond provided data.
- Missing data must reduce confidence and be mentioned in summary.
- Do not include direct medication changes unless framed as ask-user-to-confirm with clinician.
- If active frameworks are present, align recommendations with them or explicitly explain conflicts.
- Framework proposals must only add, reprioritize, or deactivate; never delete.
- If proposing framework changes, use payload:
  {"target":"framework","operations":[{"op":"upsert|update","framework_type":"...","name":"...","priority_score":0-100,"is_active":true|false,"rationale":"..."}]}
- Keep safety-focused tone and objective language."""

DEEP_SYNTHESIS_PROMPT = """You are doing monthly root-cause synthesis.
Given existing monthly synthesis output, generate additional high-value hypotheses and optional prompt tuning proposals.

Return JSON only:
{
  "root_causes": ["hypothesis 1", "hypothesis 2"],
  "prompt_adjustment_proposals": [
    {
      "title": "title",
      "rationale": "why this prompt change helps",
      "confidence": 0.0,
      "payload": {"specialist_id": "nutritionist|movement_coach|sleep_expert|supplement_auditor|safety_clinician|orchestrator", "changes": ["change"]},
      "diff_markdown": "```diff\\n...\\n```"
    }
  ],
  "confidence": 0.0
}
Rules:
- Keep outputs concise and specific."""


@dataclass
class AnalysisWindow:
    run_type: str
    period_start: date
    period_end: date


def _safe_json_loads(text: str, fallback: dict[str, Any] | list[Any] | None = None) -> dict[str, Any] | list[Any]:
    payload = (text or "").strip()
    if payload.startswith("```"):
        payload = payload.strip("`")
        if payload.lower().startswith("json"):
            payload = payload[4:].strip()
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, (dict, list)):
            return parsed
    except json.JSONDecodeError:
        pass
    if fallback is not None:
        return fallback
    return {}


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _window_for(run_type: str, target_day: date) -> AnalysisWindow:
    if run_type == "daily":
        return AnalysisWindow(run_type=run_type, period_start=target_day, period_end=target_day)
    if run_type == "weekly":
        return AnalysisWindow(run_type=run_type, period_start=target_day - timedelta(days=6), period_end=target_day)
    if run_type == "monthly":
        return AnalysisWindow(run_type=run_type, period_start=target_day - timedelta(days=29), period_end=target_day)
    raise ValueError(f"Unsupported run_type: {run_type}")


def _timezone_for_user(user: User) -> str:
    tz_name = (user.settings.timezone if user.settings else None) or "UTC"
    try:
        ZoneInfo(tz_name)
        return tz_name
    except Exception:
        return "UTC"


def _dates_inclusive(start_day: date, end_day: date) -> int:
    return max(1, (end_day - start_day).days + 1)


def _calc_slope(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return round(values[-1] - values[0], 4)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _last_completed_period_end(db: Session, user_id: int, run_type: str) -> date | None:
    row = (
        db.query(AnalysisRun.period_end)
        .filter(
            AnalysisRun.user_id == user_id,
            AnalysisRun.run_type == run_type,
            AnalysisRun.status == "completed",
        )
        .order_by(AnalysisRun.period_end.desc())
        .first()
    )
    if not row:
        return None
    return _parse_iso_date(str(row[0]))


def _monthly_due_day(year: int, month: int, preferred_day: int) -> date:
    day = min(max(1, preferred_day), calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _shift_month(year: int, month: int, delta_months: int) -> tuple[int, int]:
    month_index = (year * 12 + (month - 1)) + delta_months
    out_year = month_index // 12
    out_month = (month_index % 12) + 1
    return out_year, out_month


def _candidate_due_targets(
    run_type: str,
    reference_day: date,
    max_windows: int,
    weekly_weekday: int,
    monthly_day: int,
) -> list[date]:
    max_windows = max(1, min(max_windows, 60))
    if run_type == "daily":
        return [reference_day - timedelta(days=offset) for offset in range(max_windows)][::-1]

    if run_type == "weekly":
        latest_due = reference_day - timedelta(days=(reference_day.weekday() - weekly_weekday) % 7)
        targets = [latest_due - timedelta(days=7 * offset) for offset in range(max_windows)]
        return sorted(set(targets))

    if run_type == "monthly":
        targets: list[date] = []
        for offset in range(max_windows):
            year, month = _shift_month(reference_day.year, reference_day.month, -offset)
            due_day = _monthly_due_day(year, month, monthly_day)
            if due_day <= reference_day:
                targets.append(due_day)
        return sorted(set(targets))

    return []


def _collect_period_metrics(
    db: Session,
    user: User,
    window: AnalysisWindow,
    tz_name: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    start_dt = start_of_day(window.period_start, tz_name)
    end_dt = end_of_day(window.period_end, tz_name)
    days = _dates_inclusive(window.period_start, window.period_end)

    foods = db.query(FoodLog).filter(
        FoodLog.user_id == user.id,
        FoodLog.logged_at >= start_dt,
        FoodLog.logged_at <= end_dt,
    ).all()
    hydration = db.query(HydrationLog).filter(
        HydrationLog.user_id == user.id,
        HydrationLog.logged_at >= start_dt,
        HydrationLog.logged_at <= end_dt,
    ).all()
    vitals = db.query(VitalsLog).filter(
        VitalsLog.user_id == user.id,
        VitalsLog.logged_at >= start_dt,
        VitalsLog.logged_at <= end_dt,
    ).order_by(VitalsLog.logged_at.asc()).all()
    exercise = db.query(ExerciseLog).filter(
        ExerciseLog.user_id == user.id,
        ExerciseLog.logged_at >= start_dt,
        ExerciseLog.logged_at <= end_dt,
    ).all()
    fasting = db.query(FastingLog).filter(
        FastingLog.user_id == user.id,
        FastingLog.fast_start >= start_dt,
        FastingLog.fast_start <= end_dt,
    ).all()
    sleep = db.query(SleepLog).filter(
        SleepLog.user_id == user.id,
        sleep_log_overlaps_window(SleepLog, start_dt, end_dt),
    ).all()
    supp_logs = db.query(SupplementLog).filter(
        SupplementLog.user_id == user.id,
        SupplementLog.logged_at >= start_dt,
        SupplementLog.logged_at <= end_dt,
    ).all()
    checklist = db.query(DailyChecklistItem).filter(
        DailyChecklistItem.user_id == user.id,
        DailyChecklistItem.target_date >= window.period_start.isoformat(),
        DailyChecklistItem.target_date <= window.period_end.isoformat(),
    ).all()
    active_frameworks = active_frameworks_for_context(db, user.id)

    meds = parse_structured_list(user.settings.medications if user.settings else None)
    supps = parse_structured_list(user.settings.supplements if user.settings else None)
    expected_med = len(meds) * days
    expected_supp = len(supps) * days
    done_med = sum(1 for item in checklist if item.item_type == "medication" and item.completed)
    done_supp = sum(1 for item in checklist if item.item_type == "supplement" and item.completed)

    weight_points = [float(v.weight_kg) for v in vitals if v.weight_kg is not None]
    bp_sys_points = [int(v.bp_systolic) for v in vitals if v.bp_systolic is not None]
    bp_dia_points = [int(v.bp_diastolic) for v in vitals if v.bp_diastolic is not None]
    hr_points = [int(v.heart_rate) for v in vitals if v.heart_rate is not None]

    metrics = {
        "window": {
            "run_type": window.run_type,
            "period_start": window.period_start.isoformat(),
            "period_end": window.period_end.isoformat(),
            "days": days,
            "timezone": tz_name,
        },
        "nutrition": {
            "meal_count": len(foods),
            "calories_total": round(sum(f.calories or 0 for f in foods), 2),
            "protein_g_total": round(sum(f.protein_g or 0 for f in foods), 2),
            "carbs_g_total": round(sum(f.carbs_g or 0 for f in foods), 2),
            "fat_g_total": round(sum(f.fat_g or 0 for f in foods), 2),
            "fiber_g_total": round(sum(f.fiber_g or 0 for f in foods), 2),
            "sodium_mg_total": round(sum(f.sodium_mg or 0 for f in foods), 2),
            "calories_daily_avg": round(sum(f.calories or 0 for f in foods) / days, 2),
        },
        "hydration": {
            "total_ml": round(sum(h.amount_ml or 0 for h in hydration), 2),
            "daily_avg_ml": round(sum(h.amount_ml or 0 for h in hydration) / days, 2),
        },
        "exercise": {
            "sessions": len(exercise),
            "minutes_total": int(sum(e.duration_minutes or 0 for e in exercise)),
            "minutes_daily_avg": round(sum(e.duration_minutes or 0 for e in exercise) / days, 2),
            "calories_total": round(sum(e.calories_burned or 0 for e in exercise), 2),
        },
        "sleep": {
            "entries": len(sleep),
            "duration_avg_min": round(mean([s.duration_minutes for s in sleep if s.duration_minutes is not None]), 2)
            if any(s.duration_minutes is not None for s in sleep)
            else None,
            "qualities": [s.quality for s in sleep if s.quality],
        },
        "fasting": {
            "entries": len(fasting),
            "duration_avg_min": round(mean([f.duration_minutes for f in fasting if f.duration_minutes is not None]), 2)
            if any(f.duration_minutes is not None for f in fasting)
            else None,
        },
        "medication_adherence": {
            "expected_events": expected_med,
            "completed_events": done_med,
            "adherence_ratio": round((done_med / expected_med), 4) if expected_med else None,
        },
        "supplement_adherence": {
            "expected_events": expected_supp,
            "completed_events": done_supp,
            "adherence_ratio": round((done_supp / expected_supp), 4) if expected_supp else None,
            "logs_count": len(supp_logs),
        },
        "vitals": {
            "entries": len(vitals),
            "weight": {
                "latest_kg": weight_points[-1] if weight_points else None,
                "avg_kg": round(mean(weight_points), 3) if weight_points else None,
                "delta_kg": _calc_slope(weight_points),
            },
            "blood_pressure": {
                "avg_systolic": round(mean(bp_sys_points), 2) if bp_sys_points else None,
                "avg_diastolic": round(mean(bp_dia_points), 2) if bp_dia_points else None,
                "delta_systolic": _calc_slope([float(v) for v in bp_sys_points]) if bp_sys_points else None,
            },
            "heart_rate": {
                "avg_bpm": round(mean(hr_points), 2) if hr_points else None,
                "delta_bpm": _calc_slope([float(v) for v in hr_points]) if hr_points else None,
            },
        },
        "health_optimization_framework": {
            "active_count": len(active_frameworks),
            "active_items": [
                {
                    "id": row.id,
                    "framework_type": row.framework_type,
                    "classifier_label": row.classifier_label,
                    "name": row.name,
                    "priority_score": row.priority_score,
                    "source": row.source,
                }
                for row in active_frameworks
            ],
        },
    }

    missing_domains: list[str] = []
    if not foods:
        missing_domains.append("nutrition")
    if not hydration:
        missing_domains.append("hydration")
    if not exercise:
        missing_domains.append("exercise")
    if not vitals:
        missing_domains.append("vitals")
    if not sleep:
        missing_domains.append("sleep")
    if not active_frameworks:
        missing_domains.append("health_framework")

    risk_flags: list[str] = []
    bp = metrics["vitals"]["blood_pressure"]
    if bp["avg_systolic"] and bp["avg_systolic"] >= 140:
        risk_flags.append("bp_elevated_systolic")
    if bp["avg_diastolic"] and bp["avg_diastolic"] >= 90:
        risk_flags.append("bp_elevated_diastolic")
    sodium_avg = metrics["nutrition"]["sodium_mg_total"] / days if days else 0
    if sodium_avg >= 2300:
        risk_flags.append("sodium_high")
    if metrics["medication_adherence"]["adherence_ratio"] is not None and metrics["medication_adherence"]["adherence_ratio"] < 0.7:
        risk_flags.append("medication_adherence_low")

    return metrics, missing_domains, risk_flags


def _collect_notes_for_signals(db: Session, user: User, window: AnalysisWindow, tz_name: str) -> list[str]:
    start_dt = start_of_day(window.period_start, tz_name)
    end_dt = end_of_day(window.period_end, tz_name)
    notes: list[str] = []

    for row in db.query(FoodLog).filter(FoodLog.user_id == user.id, FoodLog.logged_at >= start_dt, FoodLog.logged_at <= end_dt).all():
        if row.notes:
            notes.append(f"Food note: {row.notes.strip()}")
    for row in db.query(VitalsLog).filter(VitalsLog.user_id == user.id, VitalsLog.logged_at >= start_dt, VitalsLog.logged_at <= end_dt).all():
        if row.notes:
            notes.append(f"Vitals note: {row.notes.strip()}")
    for row in db.query(ExerciseLog).filter(ExerciseLog.user_id == user.id, ExerciseLog.logged_at >= start_dt, ExerciseLog.logged_at <= end_dt).all():
        if row.notes:
            notes.append(f"Exercise note: {row.notes.strip()}")
    for row in db.query(SleepLog).filter(
        SleepLog.user_id == user.id,
        sleep_log_overlaps_window(SleepLog, start_dt, end_dt),
    ).all():
        if row.notes:
            notes.append(f"Sleep note: {row.notes.strip()}")
    for row in db.query(FastingLog).filter(FastingLog.user_id == user.id, FastingLog.fast_start >= start_dt, FastingLog.fast_start <= end_dt).all():
        if row.notes:
            notes.append(f"Fasting note: {row.notes.strip()}")
    for row in db.query(SupplementLog).filter(SupplementLog.user_id == user.id, SupplementLog.logged_at >= start_dt, SupplementLog.logged_at <= end_dt).all():
        if row.notes:
            notes.append(f"Supplement note: {row.notes.strip()}")

    msgs = (
        db.query(Message)
        .filter(
            Message.user_id == user.id,
            Message.role == "user",
            Message.created_at >= start_dt,
            Message.created_at <= end_dt,
        )
        .order_by(Message.created_at.desc())
        .limit(30)
        .all()
    )
    for msg in msgs:
        content = (msg.content or "").strip()
        if content:
            notes.append(f"Chat note: {content[:400]}")

    return notes[:80]


async def _extract_signal_annotations(
    db: Session,
    provider,
    user: User,
    window: AnalysisWindow,
    tz_name: str,
) -> dict[str, Any]:
    notes = _collect_notes_for_signals(db, user, window, tz_name)
    if not notes:
        return {
            "energy_signals": [],
            "stress_signals": [],
            "symptom_signals": [],
            "adherence_signals": [],
            "confidence": 0.2,
        }

    payload = {
        "period_start": window.period_start.isoformat(),
        "period_end": window.period_end.isoformat(),
        "notes": notes,
    }
    result = await provider.chat(
        messages=[{"role": "user", "content": f"{UTILITY_SIGNAL_PROMPT}\n\nData:\n{json.dumps(payload)}"}],
        model=provider.get_utility_model(),
        system="Return strict JSON only.",
        stream=False,
    )
    track_usage_from_result(
        db=db,
        user_id=user.id,
        result=result,
        model_used=provider.get_utility_model(),
        operation=f"analysis_utility_extract:{window.run_type}",
        usage_type="utility",
    )
    parsed = _safe_json_loads(
        str(result.get("content") or ""),
        fallback={
            "energy_signals": [],
            "stress_signals": [],
            "symptom_signals": [],
            "adherence_signals": [],
            "confidence": 0.2,
        },
    )
    return parsed if isinstance(parsed, dict) else {}


def _normalize_proposal_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        txt = payload.strip()
        if txt.startswith("{"):
            try:
                parsed = json.loads(txt)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {"raw": txt}
    return {"raw": str(payload)}


def _normalize_title_tokens(title: str) -> list[str]:
    raw = re.findall(r"[a-z0-9]+", (title or "").lower())
    return [t for t in raw if len(t) >= 3 and t not in PROPOSAL_TITLE_STOPWORDS]


def _proposal_title_similarity(a: str, b: str) -> float:
    a_tokens = _normalize_title_tokens(a)
    b_tokens = _normalize_title_tokens(b)
    if not a_tokens or not b_tokens:
        return 0.0
    a_norm = " ".join(a_tokens)
    b_norm = " ".join(b_tokens)
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _proposal_target(payload: dict[str, Any]) -> str:
    return str(payload.get("target", "")).strip().lower()


def _proposals_are_similar(left: AnalysisProposal, right: AnalysisProposal) -> bool:
    if left.proposal_kind != right.proposal_kind:
        return False
    l_payload = _safe_json_loads(left.proposal_json or "{}", fallback={})
    r_payload = _safe_json_loads(right.proposal_json or "{}", fallback={})
    l_target = _proposal_target(l_payload if isinstance(l_payload, dict) else {})
    r_target = _proposal_target(r_payload if isinstance(r_payload, dict) else {})
    if l_target and r_target and l_target != r_target:
        return False
    return _proposal_title_similarity(left.title or "", right.title or "") >= 0.82


def _merge_proposals_into_survivor(survivor: AnalysisProposal, duplicate: AnalysisProposal) -> None:
    survivor_payload = _safe_json_loads(survivor.proposal_json or "{}", fallback={})
    if not isinstance(survivor_payload, dict):
        survivor_payload = {}

    merged = survivor_payload.get("_merged_proposals")
    if not isinstance(merged, list):
        merged = []
    merged.append(
        {
            "proposal_id": duplicate.id,
            "analysis_run_id": duplicate.analysis_run_id,
            "title": duplicate.title,
            "confidence": duplicate.confidence,
            "created_at": duplicate.created_at.isoformat() if duplicate.created_at else None,
        }
    )
    # Keep a compact, stable dedupe trace.
    merged = merged[-40:]
    survivor_payload["_merged_proposals"] = merged
    survivor_payload["_merge_count"] = int(survivor_payload.get("_merge_count", 0) or 0) + 1
    survivor_payload["_merged_run_ids"] = sorted(
        {
            int(survivor.analysis_run_id),
            *[int(item.get("analysis_run_id")) for item in merged if item.get("analysis_run_id") is not None],
        }
    )
    survivor.proposal_json = _json_dump(survivor_payload)

    if duplicate.confidence is not None:
        if survivor.confidence is None:
            survivor.confidence = duplicate.confidence
        else:
            survivor.confidence = max(float(survivor.confidence), float(duplicate.confidence))

    dup_rationale = (duplicate.rationale or "").strip()
    if dup_rationale and dup_rationale not in (survivor.rationale or ""):
        survivor.rationale = f"{(survivor.rationale or '').strip()} | {dup_rationale}".strip(" |")

    if not survivor.diff_markdown and duplicate.diff_markdown:
        survivor.diff_markdown = duplicate.diff_markdown


def combine_similar_pending_proposals(
    db: Session,
    user_id: int,
) -> dict[str, int]:
    rows = (
        db.query(AnalysisProposal)
        .filter(
            AnalysisProposal.user_id == user_id,
            AnalysisProposal.status == "pending",
        )
        .order_by(AnalysisProposal.created_at.desc(), AnalysisProposal.id.desc())
        .all()
    )
    survivors: list[AnalysisProposal] = []
    merged = 0

    for row in rows:
        match = next((candidate for candidate in survivors if _proposals_are_similar(candidate, row)), None)
        if not match:
            survivors.append(row)
            continue
        _merge_proposals_into_survivor(match, row)
        db.delete(row)
        merged += 1

    return {"merged": merged, "remaining": len(survivors)}


def _prepare_proposal_rows(
    run: AnalysisRun,
    raw_proposals: list[dict[str, Any]],
) -> list[AnalysisProposal]:
    rows: list[AnalysisProposal] = []
    for item in raw_proposals:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("proposal_kind", "guidance_update")).strip().lower()
        if kind not in PROPOSAL_KINDS:
            kind = "guidance_update"
        title = str(item.get("title", "")).strip() or "Adaptive guidance proposal"
        rationale = str(item.get("rationale", "")).strip() or "Generated from longitudinal analysis."
        confidence_raw = item.get("confidence")
        try:
            confidence = float(confidence_raw) if confidence_raw is not None else None
        except (TypeError, ValueError):
            confidence = None
        row = AnalysisProposal(
            user_id=run.user_id,
            analysis_run_id=run.id,
            proposal_kind=kind,
            status="pending",
            title=title,
            rationale=rationale,
            confidence=confidence,
            requires_approval=True,
            proposal_json=_json_dump(_normalize_proposal_payload(item.get("payload", {}))),
            diff_markdown=str(item.get("diff_markdown", "")).strip() or None,
        )
        rows.append(row)
    return rows


async def run_longitudinal_analysis(
    db: Session,
    user: User,
    run_type: str,
    target_date: date | None = None,
    trigger: str = "manual",
    force: bool = False,
) -> AnalysisRun:
    run_type = run_type.strip().lower()
    if run_type not in VALID_RUN_TYPES:
        raise ValueError(f"Invalid run_type: {run_type}")
    if not user.settings:
        raise ValueError("User settings are missing")

    tz_name = _timezone_for_user(user)
    target_day = target_date or today_for_tz(tz_name)
    window = _window_for(run_type, target_day)
    existing = (
        db.query(AnalysisRun)
        .filter(
            AnalysisRun.user_id == user.id,
            AnalysisRun.run_type == run_type,
            AnalysisRun.period_start == window.period_start.isoformat(),
            AnalysisRun.period_end == window.period_end.isoformat(),
        )
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        .first()
    )

    run: AnalysisRun
    if existing:
        if not force and existing.status in {"running", "completed"}:
            return existing
        db.query(AnalysisProposal).filter(AnalysisProposal.analysis_run_id == existing.id).delete(synchronize_session=False)
        existing.status = "running"
        existing.confidence = None
        existing.metrics_json = None
        existing.missing_data_json = None
        existing.risk_flags_json = None
        existing.synthesis_json = None
        existing.summary_markdown = f"Analysis queued by {trigger}."
        existing.completed_at = None
        existing.error_message = None
        existing.used_utility_model = None
        existing.used_reasoning_model = None
        existing.used_deep_model = None
        existing.created_at = datetime.now(timezone.utc)
        run = existing
    else:
        run = AnalysisRun(
            user_id=user.id,
            run_type=run_type,
            period_start=window.period_start.isoformat(),
            period_end=window.period_end.isoformat(),
            status="running",
            summary_markdown=f"Analysis queued by {trigger}.",
            created_at=datetime.now(timezone.utc),
        )
        db.add(run)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = (
            db.query(AnalysisRun)
            .filter(
                AnalysisRun.user_id == user.id,
                AnalysisRun.run_type == run_type,
                AnalysisRun.period_start == window.period_start.isoformat(),
                AnalysisRun.period_end == window.period_end.isoformat(),
            )
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
            .first()
        )
        if winner is None:
            raise
        run = winner
        if not force and run.status in {"running", "completed"}:
            return run
        db.query(AnalysisProposal).filter(AnalysisProposal.analysis_run_id == run.id).delete(synchronize_session=False)
        run.status = "running"
        run.confidence = None
        run.metrics_json = None
        run.missing_data_json = None
        run.risk_flags_json = None
        run.synthesis_json = None
        run.summary_markdown = f"Analysis queued by {trigger}."
        run.completed_at = None
        run.error_message = None
        run.used_utility_model = None
        run.used_reasoning_model = None
        run.used_deep_model = None
        run.created_at = datetime.now(timezone.utc)
        db.commit()

    db.refresh(run)

    metrics, missing_domains, base_risk_flags = _collect_period_metrics(db, user, window, tz_name)
    synthesis_payload: dict[str, Any] = {}
    risk_flags: list[dict[str, Any]] = [
        {
            "code": code,
            "severity": "medium" if "elevated" in code else "low",
            "title": code.replace("_", " ").title(),
            "detail": "Detected from deterministic metrics.",
        }
        for code in base_risk_flags
    ]
    summary_markdown = ""
    confidence = 0.4 if missing_domains else 0.6
    utility_model = None
    reasoning_model = None
    deep_model = None

    try:
        if user.settings.api_key_encrypted:
            api_key = decrypt_api_key(user.settings.api_key_encrypted)
            provider = get_provider(
                user.settings.ai_provider,
                api_key,
                reasoning_model=user.settings.reasoning_model,
                utility_model=user.settings.utility_model,
                deep_thinking_model=user.settings.deep_thinking_model,
            )
            utility_model = provider.get_utility_model()
            reasoning_model = provider.get_reasoning_model()
            deep_model = provider.get_deep_thinking_model()

            signal_annotations = await _extract_signal_annotations(db, provider, user, window, tz_name)

            synthesis_input = {
                "window": {
                    "run_type": window.run_type,
                    "period_start": window.period_start.isoformat(),
                    "period_end": window.period_end.isoformat(),
                    "timezone": tz_name,
                    "trigger": trigger,
                },
                "profile": format_user_profile(user.settings),
                "metrics": metrics,
                "missing_domains": missing_domains,
                "base_risk_flags": base_risk_flags,
                "signal_annotations": signal_annotations,
            }
            reasoning_result = await provider.chat(
                messages=[
                    {
                        "role": "user",
                        "content": f"{REASONING_SYNTHESIS_PROMPT}\n\nInput:\n{json.dumps(synthesis_input)}",
                    }
                ],
                model=provider.get_reasoning_model(),
                system="Return strict JSON only.",
                stream=False,
            )
            track_usage_from_result(
                db=db,
                user_id=user.id,
                result=reasoning_result,
                model_used=provider.get_reasoning_model(),
                operation=f"analysis_reasoning_synthesis:{window.run_type}",
                usage_type="reasoning",
            )
            synthesis_payload_raw = _safe_json_loads(str(reasoning_result.get("content") or ""), fallback={})
            synthesis_payload = synthesis_payload_raw if isinstance(synthesis_payload_raw, dict) else {}
            summary_markdown = str(synthesis_payload.get("summary_markdown", "")).strip()
            confidence_raw = synthesis_payload.get("confidence")
            try:
                if confidence_raw is not None:
                    confidence = float(confidence_raw)
            except (TypeError, ValueError):
                pass

            ai_risk_flags = synthesis_payload.get("risk_flags", [])
            if isinstance(ai_risk_flags, list):
                for row in ai_risk_flags:
                    if isinstance(row, dict):
                        risk_flags.append(row)

            if run_type == "monthly":
                deep_input = {
                    "metrics": metrics,
                    "current_synthesis": synthesis_payload,
                    "missing_domains": missing_domains,
                    "profile": format_user_profile(user.settings),
                }
                deep_result = await provider.chat(
                    messages=[{"role": "user", "content": f"{DEEP_SYNTHESIS_PROMPT}\n\nInput:\n{json.dumps(deep_input)}"}],
                    model=provider.get_deep_thinking_model(),
                    system="Return strict JSON only.",
                    stream=False,
                )
                track_usage_from_result(
                    db=db,
                    user_id=user.id,
                    result=deep_result,
                    model_used=provider.get_deep_thinking_model(),
                    operation="analysis_deep_synthesis:monthly",
                    usage_type="deep_thinking",
                )
                deep_payload_raw = _safe_json_loads(str(deep_result.get("content") or ""), fallback={})
                deep_payload = deep_payload_raw if isinstance(deep_payload_raw, dict) else {}
                synthesis_payload["deep_thinking"] = deep_payload
                deep_conf_raw = deep_payload.get("confidence")
                try:
                    if deep_conf_raw is not None:
                        confidence = max(confidence, float(deep_conf_raw))
                except (TypeError, ValueError):
                    pass

                prompt_props = deep_payload.get("prompt_adjustment_proposals", [])
                if isinstance(prompt_props, list):
                    proposals = synthesis_payload.setdefault("proposals", [])
                    if isinstance(proposals, list):
                        for p in prompt_props:
                            if isinstance(p, dict):
                                p = dict(p)
                                p["proposal_kind"] = "prompt_adjustment"
                                proposals.append(p)
        else:
            summary_markdown = "API key not configured. Generated deterministic metrics only."
            synthesis_payload = {"recommendations": [], "proposals": []}

        proposals_raw = synthesis_payload.get("proposals", [])
        if not isinstance(proposals_raw, list):
            proposals_raw = []

        run.confidence = max(0.0, min(float(confidence), 1.0))
        run.status = "completed"
        run.metrics_json = _json_dump(metrics)
        run.missing_data_json = _json_dump(missing_domains)
        run.risk_flags_json = _json_dump(risk_flags)
        run.synthesis_json = _json_dump(synthesis_payload)
        run.summary_markdown = summary_markdown or "No summary generated."
        run.used_utility_model = utility_model
        run.used_reasoning_model = reasoning_model
        run.used_deep_model = deep_model
        run.completed_at = datetime.now(timezone.utc)

        for proposal in _prepare_proposal_rows(run, proposals_raw):
            db.add(proposal)

        # Auto-combine repetitive pending proposals so users don't see duplicates
        # across daily/weekly/monthly windows with similar intent.
        combine_similar_pending_proposals(db, user.id)

        db.commit()
        if bool(getattr(app_settings, "ANALYSIS_AUTO_APPLY_PROPOSALS", False)):
            pending_rows = (
                db.query(AnalysisProposal)
                .filter(
                    AnalysisProposal.user_id == user.id,
                    AnalysisProposal.analysis_run_id == run.id,
                    AnalysisProposal.status == "pending",
                )
                .order_by(AnalysisProposal.id.asc())
                .all()
            )
            for proposal in pending_rows:
                try:
                    review_proposal(
                        db=db,
                        user=user,
                        proposal_id=int(proposal.id),
                        action="apply",
                        note="Auto-applied by adaptation engine",
                    )
                except Exception as exc:
                    logger.warning("Auto-apply failed for proposal %s (run %s): %s", proposal.id, run.id, exc)
        db.refresh(run)
        return run

    except Exception as exc:
        logger.exception("Longitudinal analysis failed")
        run.status = "failed"
        run.metrics_json = _json_dump(metrics)
        run.missing_data_json = _json_dump(missing_domains)
        run.risk_flags_json = _json_dump(risk_flags)
        run.error_message = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        run.used_utility_model = utility_model
        run.used_reasoning_model = reasoning_model
        run.used_deep_model = deep_model
        db.commit()
        raise


async def run_due_analyses(db: Session, user: User, trigger: str = "chat") -> list[AnalysisRun]:
    if not app_settings.ENABLE_LONGITUDINAL_ANALYSIS:
        return []
    if not user.settings:
        return []

    tz_name = _timezone_for_user(user)
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(ZoneInfo(tz_name))
    reference_day = now_local.date()
    if now_local.hour < app_settings.ANALYSIS_DAILY_HOUR_LOCAL:
        reference_day = reference_day - timedelta(days=1)

    runs: list[AnalysisRun] = []
    is_chat_trigger = str(trigger or "").strip().lower().startswith("chat")
    configured_max = (
        int(getattr(app_settings, "ANALYSIS_MAX_CATCHUP_WINDOWS_CHAT", 1))
        if is_chat_trigger
        else int(getattr(app_settings, "ANALYSIS_MAX_CATCHUP_WINDOWS", 6))
    )
    max_windows = max(1, min(configured_max, 60))
    weekly_weekday = max(0, min(int(app_settings.ANALYSIS_WEEKLY_WEEKDAY_LOCAL), 6))
    monthly_day = max(1, min(int(app_settings.ANALYSIS_MONTHLY_DAY_LOCAL), 31))

    for run_type in ("daily", "weekly", "monthly"):
        last_completed_end = _last_completed_period_end(db, user.id, run_type)
        candidates = _candidate_due_targets(
            run_type=run_type,
            reference_day=reference_day,
            max_windows=max_windows,
            weekly_weekday=weekly_weekday,
            monthly_day=monthly_day,
        )
        if last_completed_end is not None:
            candidates = [day for day in candidates if day > last_completed_end]
        for target_day in candidates:
            try:
                run = await run_longitudinal_analysis(
                    db=db,
                    user=user,
                    run_type=run_type,
                    target_date=target_day,
                    trigger=trigger,
                    force=False,
                )
                runs.append(run)
            except Exception as exc:
                logger.warning("Due %s analysis failed for user %s (%s): %s", run_type, user.id, target_day, exc)

    return runs


async def run_due_analyses_for_user_id(user_id: int, trigger: str = "chat_async") -> None:
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            return
        try:
            await run_due_analyses(db=db, user=user, trigger=trigger)
        except Exception as exc:
            logger.warning("Async due analysis failed for user %s: %s", user_id, exc)
    finally:
        db.close()


def serialize_analysis_run(run: AnalysisRun) -> dict[str, Any]:
    missing_data = _safe_json_loads(run.missing_data_json or "[]", fallback=[])
    risk_flags = _safe_json_loads(run.risk_flags_json or "[]", fallback=[])
    metrics = _safe_json_loads(run.metrics_json or "{}", fallback={})
    synthesis = _safe_json_loads(run.synthesis_json or "{}", fallback={})
    return {
        "id": run.id,
        "user_id": run.user_id,
        "run_type": run.run_type,
        "period_start": run.period_start,
        "period_end": run.period_end,
        "status": run.status,
        "confidence": run.confidence,
        "used_utility_model": run.used_utility_model,
        "used_reasoning_model": run.used_reasoning_model,
        "used_deep_model": run.used_deep_model,
        "metrics": metrics if isinstance(metrics, dict) else {},
        "missing_data": missing_data if isinstance(missing_data, list) else [],
        "risk_flags": risk_flags if isinstance(risk_flags, list) else [],
        "synthesis": synthesis if isinstance(synthesis, dict) else {},
        "summary_markdown": run.summary_markdown,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_message": run.error_message,
    }


def serialize_analysis_proposal(row: AnalysisProposal) -> dict[str, Any]:
    payload = _safe_json_loads(row.proposal_json or "{}", fallback={})
    payload_obj = payload if isinstance(payload, dict) else {}
    merge_count = int(payload_obj.get("_merge_count", 0) or 0)
    merged_run_ids = payload_obj.get("_merged_run_ids", [])
    if not isinstance(merged_run_ids, list):
        merged_run_ids = []
    merged_run_ids = [int(v) for v in merged_run_ids if str(v).strip().isdigit()]
    return {
        "id": row.id,
        "user_id": row.user_id,
        "analysis_run_id": row.analysis_run_id,
        "proposal_kind": row.proposal_kind,
        "status": row.status,
        "title": row.title,
        "rationale": row.rationale,
        "confidence": row.confidence,
        "requires_approval": bool(row.requires_approval),
        "payload": payload_obj,
        "merge_count": merge_count,
        "merged_run_ids": merged_run_ids,
        "diff_markdown": row.diff_markdown,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "reviewer_user_id": row.reviewer_user_id,
        "review_note": row.review_note,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def _apply_framework_proposal(
    db: Session,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    operations = payload.get("operations")
    if not isinstance(operations, list):
        return {"applied": 0, "errors": ["Missing framework operations payload"]}

    applied = 0
    errors: list[str] = []
    undo_operations: list[dict[str, Any]] = []

    def _snapshot_framework(row: HealthOptimizationFramework) -> dict[str, Any]:
        metadata = _safe_json_loads(row.metadata_json or "{}", fallback={})
        return {
            "framework_id": int(row.id),
            "framework_type": str(row.framework_type),
            "name": str(row.name),
            "priority_score": int(row.priority_score or 0),
            "is_active": bool(row.is_active),
            "source": str(row.source or "adaptive"),
            "rationale": str(row.rationale or ""),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }

    for idx, op in enumerate(operations):
        if not isinstance(op, dict):
            errors.append(f"Operation {idx} is not an object")
            continue
        op_kind = str(op.get("op", "upsert")).strip().lower()
        if op_kind == "delete":
            errors.append(f"Operation {idx}: delete is not allowed for adaptive framework updates")
            continue

        try:
            if op_kind == "update":
                framework_id = int(op.get("framework_id"))
                before = (
                    db.query(HealthOptimizationFramework)
                    .filter(HealthOptimizationFramework.user_id == user.id, HealthOptimizationFramework.id == framework_id)
                    .first()
                )
                if not before:
                    errors.append(f"Operation {idx}: framework_id {framework_id} not found")
                    continue
                undo_operations.append({"op": "restore", "snapshot": _snapshot_framework(before)})
                update_framework(
                    db=db,
                    user_id=user.id,
                    framework_id=framework_id,
                    framework_type=op.get("framework_type"),
                    name=op.get("name"),
                    priority_score=op.get("priority_score"),
                    is_active=op.get("is_active"),
                    source="adaptive",
                    rationale=op.get("rationale"),
                    metadata={"applied_by": "analysis_proposal"},
                    commit=False,
                )
            else:
                framework_type = str(op.get("framework_type", ""))
                framework_name = str(op.get("name", ""))
                before = None
                if framework_name.strip():
                    normalized_name = normalize_framework_name(framework_name)
                    if normalized_name:
                        before = (
                            db.query(HealthOptimizationFramework)
                            .filter(
                                HealthOptimizationFramework.user_id == user.id,
                                HealthOptimizationFramework.normalized_name == normalized_name,
                            )
                            .first()
                        )
                if before:
                    undo_operations.append({"op": "restore", "snapshot": _snapshot_framework(before)})
                row, _ = upsert_framework(
                    db=db,
                    user_id=user.id,
                    framework_type=framework_type,
                    name=framework_name,
                    priority_score=op.get("priority_score"),
                    is_active=op.get("is_active"),
                    source="adaptive",
                    rationale=op.get("rationale"),
                    metadata={"applied_by": "analysis_proposal"},
                    commit=False,
                )
                if not before:
                    undo_operations.append({"op": "delete", "framework_id": int(row.id)})
            applied += 1
        except Exception as exc:
            errors.append(f"Operation {idx}: {exc}")

    return {"applied": applied, "errors": errors, "undo_operations": undo_operations}


def _undo_framework_proposal(
    db: Session,
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    undo_operations = payload.get("_undo_operations")
    if not isinstance(undo_operations, list) or not undo_operations:
        return {"applied": 0, "errors": ["No undo operations available for this proposal"]}

    applied = 0
    errors: list[str] = []
    for idx, op in enumerate(reversed(undo_operations)):
        if not isinstance(op, dict):
            errors.append(f"Undo operation {idx} is not an object")
            continue
        op_kind = str(op.get("op", "")).strip().lower()
        try:
            if op_kind == "delete":
                framework_id = int(op.get("framework_id"))
                try:
                    delete_framework(
                        db=db,
                        user_id=user.id,
                        framework_id=framework_id,
                        allow_seed_delete=True,
                        commit=False,
                    )
                    applied += 1
                except Exception:
                    errors.append(f"Undo operation {idx}: framework_id {framework_id} was not found")
            elif op_kind == "restore":
                snapshot = op.get("snapshot")
                if not isinstance(snapshot, dict):
                    errors.append(f"Undo operation {idx}: missing snapshot")
                    continue
                framework_id = int(snapshot.get("framework_id", 0) or 0)
                existing = (
                    db.query(HealthOptimizationFramework)
                    .filter(HealthOptimizationFramework.user_id == user.id, HealthOptimizationFramework.id == framework_id)
                    .first()
                    if framework_id > 0
                    else None
                )
                if existing:
                    update_framework(
                        db=db,
                        user_id=user.id,
                        framework_id=framework_id,
                        framework_type=snapshot.get("framework_type"),
                        name=snapshot.get("name"),
                        priority_score=snapshot.get("priority_score"),
                        is_active=snapshot.get("is_active"),
                        source=snapshot.get("source"),
                        rationale=snapshot.get("rationale"),
                        metadata=snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {},
                        commit=False,
                    )
                else:
                    upsert_framework(
                        db=db,
                        user_id=user.id,
                        framework_type=str(snapshot.get("framework_type", "")),
                        name=str(snapshot.get("name", "")),
                        priority_score=snapshot.get("priority_score"),
                        is_active=snapshot.get("is_active"),
                        source=snapshot.get("source"),
                        rationale=snapshot.get("rationale"),
                        metadata=snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {},
                        commit=False,
                    )
                applied += 1
            else:
                errors.append(f"Undo operation {idx}: unsupported op '{op_kind}'")
        except Exception as exc:
            errors.append(f"Undo operation {idx}: {exc}")

    return {"applied": applied, "errors": errors}


def review_proposal(
    db: Session,
    user: User,
    proposal_id: int,
    action: str,
    note: str | None = None,
) -> AnalysisProposal:
    proposal = (
        db.query(AnalysisProposal)
        .filter(AnalysisProposal.id == proposal_id, AnalysisProposal.user_id == user.id)
        .first()
    )
    if not proposal:
        raise ValueError("Proposal not found")

    action_norm = action.strip().lower()
    if action_norm not in {"approve", "reject", "apply", "undo"}:
        raise ValueError("Action must be approve, reject, apply, or undo")
    apply_note: str | None = None
    if action_norm == "approve":
        proposal.status = "approved"
    elif action_norm == "reject":
        proposal.status = "rejected"
    elif action_norm == "apply":
        proposal.status = "applied"
        proposal.applied_at = datetime.now(timezone.utc)
        payload = _safe_json_loads(proposal.proposal_json or "{}", fallback={})
        if isinstance(payload, dict) and str(payload.get("target", "")).strip().lower() == "framework":
            apply_result = _apply_framework_proposal(db, user, payload)
            if apply_result["errors"]:
                apply_note = "; ".join(apply_result["errors"])
            undo_ops = apply_result.get("undo_operations")
            if isinstance(undo_ops, list):
                payload["_undo_operations"] = undo_ops
                proposal.proposal_json = _json_dump(payload)
            if apply_result["applied"] <= 0:
                proposal.status = "approved"
                proposal.applied_at = None
        proposal.requires_approval = False
    else:
        if proposal.status not in {"approved", "applied"}:
            raise ValueError("Only approved/applied proposals can be undone")
        payload = _safe_json_loads(proposal.proposal_json or "{}", fallback={})
        if proposal.status == "applied" and isinstance(payload, dict) and str(payload.get("target", "")).strip().lower() == "framework":
            undo_result = _undo_framework_proposal(db, user, payload)
            if undo_result["errors"]:
                apply_note = "; ".join(undo_result["errors"])
        proposal.status = "rejected"
        proposal.applied_at = None
        proposal.requires_approval = False

    if proposal.status not in PROPOSAL_STATUSES:
        proposal.status = "pending"
    proposal.reviewed_at = datetime.now(timezone.utc)
    proposal.reviewer_user_id = user.id
    review_note_parts = [part for part in [(note or "").strip(), (apply_note or "").strip()] if part]
    proposal.review_note = " | ".join(review_note_parts) if review_note_parts else None
    db.commit()
    db.refresh(proposal)
    return proposal


def get_approved_guidance_for_context(db: Session, user: User, limit: int = 6) -> str:
    rows = (
        db.query(AnalysisProposal)
        .filter(
            AnalysisProposal.user_id == user.id,
            AnalysisProposal.status.in_(["approved", "applied"]),
        )
        .order_by(AnalysisProposal.reviewed_at.desc(), AnalysisProposal.created_at.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return ""
    lines = ["## Approved Adaptive Guidance"]
    for row in rows:
        payload = _safe_json_loads(row.proposal_json or "{}", fallback={})
        payload_obj = payload if isinstance(payload, dict) else {}
        target = str(payload_obj.get("target", "")).strip()
        line = f"- [{row.proposal_kind}] {row.title}"
        if target:
            line += f" (target: {target})"
        lines.append(line)
        changes = payload_obj.get("changes")
        if isinstance(changes, list):
            for change in changes[:3]:
                c = str(change).strip()
                if c:
                    lines.append(f"  - {c}")
        operations = payload_obj.get("operations")
        if isinstance(operations, list):
            for op in operations[:3]:
                if not isinstance(op, dict):
                    continue
                op_kind = str(op.get("op", "upsert")).strip().lower()
                op_name = str(op.get("name", "")).strip()
                op_type = str(op.get("framework_type", "")).strip()
                op_score = op.get("priority_score")
                if op_name:
                    detail = f"{op_kind} {op_name}"
                    if op_type:
                        detail += f" ({op_type})"
                    if op_score is not None:
                        detail += f" score={op_score}"
                    lines.append(f"  - {detail}")
    return "\n".join(lines)
