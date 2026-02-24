from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from ai.orchestrator import (
    _looks_like_food_followup_answer,
    _looks_like_food_logging_message,
    _looks_like_food_planning_question,
    _minimal_food_payload_from_message,
)
from ai.specialist_router import _heuristic_category


def test_mixed_food_question_routes_as_log_food():
    category = _heuristic_category("I had a banana and whole wheat bagel, is that okay for lunch?")
    assert category == "log_food"


def test_food_planning_question_routes_as_nutrition_question():
    category = _heuristic_category("Can I have a banana for lunch?")
    assert category == "ask_nutrition"


def test_food_logging_detector_handles_common_meal_phrases():
    assert _looks_like_food_logging_message("for lunch I had a banana and bagel with cream cheese")
    assert _looks_like_food_logging_message("Lunch: protein shake + apple")
    assert _looks_like_food_logging_message("i drank 16 oz water and had eggs")


def test_followup_answer_detector_accepts_short_meal_replies():
    assert _looks_like_food_followup_answer("banana and whole wheat bagel with cream cheese")
    assert _looks_like_food_followup_answer("apple, almonds, and protein shake")
    assert not _looks_like_food_followup_answer("yes")
    assert not _looks_like_food_followup_answer("no")


def test_minimal_food_payload_low_confidence_marks_notes():
    payload = _minimal_food_payload_from_message("banana and bagel", low_confidence=True)
    assert payload["meal_label"] == "Meal"
    assert isinstance(payload["items"], list) and payload["items"]
    assert "low-confidence" in str(payload.get("notes", "")).lower()


def test_food_planning_question_detector_avoids_false_logs():
    assert _looks_like_food_planning_question("Can I have a banana for lunch?")
    assert _looks_like_food_planning_question("Should I eat oats for breakfast?")
    assert not _looks_like_food_planning_question("I had a banana for lunch")
    assert not _looks_like_food_planning_question("I had a banana for lunch, is that okay?")
