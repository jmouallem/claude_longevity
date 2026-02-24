from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.base import ToolExecutionError  # noqa: E402
from tools.write_tools import _coerce_float_field, _to_float_relaxed  # noqa: E402


def test_to_float_relaxed_parses_common_nutrition_strings():
    assert _to_float_relaxed("220 kcal", "calories") == 220.0
    assert _to_float_relaxed("1,200 mg", "sodium_mg") == 1200.0
    assert _to_float_relaxed("~30", "carbs_g") == 30.0
    assert _to_float_relaxed("<1g", "protein_g") == 0.5


def test_coerce_float_field_lenient_mode_never_raises_for_bad_nutrition_strings():
    out = _coerce_float_field({"protein_g": "<1g"}, "protein_g", strict=False)
    assert out == 0.5
    out = _coerce_float_field({"fat_g": "unknown"}, "fat_g", strict=False)
    assert out is None
    out = _coerce_float_field({"fiber_g": "abc"}, "fiber_g", strict=False)
    assert out is None


def test_coerce_float_field_strict_mode_still_raises():
    with pytest.raises(ToolExecutionError):
        _coerce_float_field({"protein_g": "<1g"}, "protein_g", strict=True)

