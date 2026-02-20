"""Unit conversion helpers for persisted user preferences."""

KG_PER_LB = 0.45359237
CM_PER_IN = 2.54
ML_PER_FL_OZ = 29.5735295625


def kg_to_lb(kg: float) -> float:
    return kg / KG_PER_LB


def lb_to_kg(lb: float) -> float:
    return lb * KG_PER_LB


def cm_to_ft_in(cm: float) -> tuple[int, int]:
    total_inches = cm / CM_PER_IN
    feet = int(total_inches // 12)
    inches = int(round(total_inches - (feet * 12)))
    if inches == 12:
        feet += 1
        inches = 0
    return feet, inches


def ml_to_oz(ml: float) -> float:
    return ml / ML_PER_FL_OZ


def oz_to_ml(oz: float) -> float:
    return oz * ML_PER_FL_OZ
