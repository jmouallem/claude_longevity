"""Shared helpers for structured medication / supplement items.

Canonical storage format (JSON text in DB):
    [{"name": "Candesartan", "dose": "4mg", "timing": "morning"}, ...]
"""

import json
import re
from typing import TypedDict

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class StructuredItem(TypedDict, total=False):
    name: str
    dose: str
    timing: str


# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

DOSE_RE = re.compile(
    r"\b(\d[\d,.\s]*(mcg|mg|g|kg|iu|ml|units?|tabs?|caps?|drops?))\b",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

SUPP_STOPWORDS = {
    "vitamin", "supplement", "daily", "dose", "extra", "strength",
    "plus", "with", "per", "and", "the", "for", "take", "taking",
}
SHORT_SUPP_TOKENS = {"d3", "b12", "coq10", "q10", "omega3", "omega"}

SUPP_ALIAS_MAP = {
    "d3": "Vitamin D3",
    "vit d3": "Vitamin D3",
    "vitamin d": "Vitamin D3",
    "b12": "Vitamin B12",
    "vit b12": "Vitamin B12",
    "coq10": "Coenzyme Q10",
    "omega3": "Omega-3",
    "omega 3": "Omega-3",
    "omega-3": "Omega-3",
}

FAMILY_KEYWORDS: dict[str, list[str]] = {
    "omega3": ["omega3", "omega-3", "omega 3"],
    "d3": ["d3", "vitamin d", "vit d"],
    "b12": ["b12", "vitamin b12", "vit b12"],
    "coq10": ["coq10", "q10"],
}

MEDICATION_KEYWORDS = {
    "ezetimibe", "statin", "metformin", "lisinopril", "losartan",
    "candesartan", "amlodipine", "hydrochlorothiazide", "atorvastatin",
    "rosuvastatin", "simvastatin", "levothyroxine", "insulin", "semaglutide",
}

GENERIC_MEDICATION_PHRASES = {
    "med",
    "meds",
    "medication",
    "medications",
    "my med",
    "my meds",
    "my medication",
    "my medications",
    "morning med",
    "morning meds",
    "morning medication",
    "morning medications",
    "evening med",
    "evening meds",
    "night med",
    "night meds",
    "blood pressure med",
    "blood pressure meds",
    "blood pressure medication",
    "blood pressure medications",
    "bp med",
    "bp meds",
    "bp medication",
    "bp medications",
}

GENERIC_SUPPLEMENT_PHRASES = {
    "supplement",
    "supplements",
    "my supplement",
    "my supplements",
    "vitamin",
    "vitamins",
    "my vitamin",
    "my vitamins",
    "morning supplements",
    "evening supplements",
    "daily supplements",
}


# ---------------------------------------------------------------------------
# Family / token helpers
# ---------------------------------------------------------------------------

def family_from_text(text: str) -> str | None:
    t = text.lower()
    for family, keywords in FAMILY_KEYWORDS.items():
        if any(k in t for k in keywords):
            return family
    return None


def family_matches_item(family: str, item_name: str) -> bool:
    keywords = FAMILY_KEYWORDS.get(family, [])
    low = item_name.lower()
    return any(k in low for k in keywords)


def supp_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for t in TOKEN_RE.findall(text.lower()):
        if t == "omega3":
            out.update(("omega3", "omega"))
            continue
        if t in SUPP_STOPWORDS:
            continue
        if len(t) >= 3 or t in SHORT_SUPP_TOKENS:
            out.add(t)
    return out


def is_low_signal(name: str) -> bool:
    """True for orphan fragments like 'drops', 'omega 3', '4 daily'."""
    t = " ".join(name.lower().split())
    tokens = supp_tokens(t)
    if not tokens:
        return True
    if len(tokens) == 1 and next(iter(tokens)) in SHORT_SUPP_TOKENS:
        return True
    # Pure dose/intake fragments like "4 drops daily", "2 daily"
    if re.match(r"^\d+\s*(drops?|daily|caps?|tabs?)", t):
        return True
    return False


def looks_like_medication(name: str) -> bool:
    t = name.lower()
    return any(k in t for k in MEDICATION_KEYWORDS)


def _normalize_name_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def is_generic_medication_name(name: str) -> bool:
    t = _normalize_name_text(name)
    if not t:
        return True
    if t in GENERIC_MEDICATION_PHRASES:
        return True
    if re.fullmatch(r"(my\s+)?(morning|evening|night|bedtime|daily)?\s*(med|meds|medication|medications)", t):
        return True
    if "med" in t and not looks_like_medication(t):
        return True
    return False


def is_generic_supplement_name(name: str) -> bool:
    t = _normalize_name_text(name)
    if not t:
        return True
    if t in GENERIC_SUPPLEMENT_PHRASES:
        return True
    if re.fullmatch(r"(my\s+)?(morning|evening|night|daily)?\s*(supplement|supplements|vitamin|vitamins)", t):
        return True
    return False


# ---------------------------------------------------------------------------
# Conversion: string → structured
# ---------------------------------------------------------------------------

def to_structured(entry) -> StructuredItem:
    """Convert a legacy string or dict into a StructuredItem."""
    if isinstance(entry, dict):
        return StructuredItem(
            name=str(entry.get("name", "")).strip(),
            dose=str(entry.get("dose", "")).strip(),
            timing=str(entry.get("timing", "")).strip(),
        )

    text = " ".join(str(entry).split()).strip()
    # Try to split "Candesartan 4mg" into name + dose
    m = DOSE_RE.search(text)
    if m:
        dose = m.group(0).strip()
        name = (text[:m.start()] + text[m.end():]).strip()
        # Clean up connectors
        name = re.sub(r"\s*[+\-,]\s*$", "", name).strip()
        name = re.sub(r"^\s*[+\-,]\s*", "", name).strip()
        if not name:
            name = dose
            dose = ""
        return StructuredItem(name=name, dose=dose, timing="")

    return StructuredItem(name=text, dose="", timing="")


def structured_to_display(item: StructuredItem) -> str:
    """Produce a human-readable string from a structured item."""
    parts = [item.get("name", "")]
    dose = item.get("dose", "")
    timing = item.get("timing", "")
    if dose:
        parts[0] += f" ({dose})"
    if timing:
        parts[0] += f" — {timing}"
    return parts[0]


# ---------------------------------------------------------------------------
# Parse stored JSON → list[StructuredItem]
# ---------------------------------------------------------------------------

def parse_structured_list(raw: str | None) -> list[StructuredItem]:
    """Parse DB JSON text into a list of StructuredItem.

    Handles both legacy string arrays and new structured arrays.
    """
    if not raw:
        return []
    txt = raw.strip()
    if not txt:
        return []

    items: list[StructuredItem] = []

    if txt.startswith("["):
        try:
            arr = json.loads(txt)
            if isinstance(arr, list):
                for entry in arr:
                    if isinstance(entry, str) and entry.strip():
                        items.append(to_structured(entry))
                    elif isinstance(entry, dict):
                        items.append(to_structured(entry))
                return items
        except json.JSONDecodeError:
            pass

    # Fallback: avoid comma splitting because doses like "1,200 mcg" are common.
    # Support semicolon/newline separated legacy inputs, otherwise treat as one item.
    if ";" in txt or "\n" in txt:
        for piece in re.split(r"[;\n]+", txt):
            piece = piece.strip()
            if piece:
                items.append(to_structured(piece))
    elif txt:
        items.append(to_structured(txt))

    return items


# ---------------------------------------------------------------------------
# Merge structured items (used by orchestrator and migration)
# ---------------------------------------------------------------------------

def merge_structured_items(
    existing_json: str | None,
    new_items: list[StructuredItem],
) -> str | None:
    """Merge new items into existing structured list.

    - Matches by supplement family or token overlap on name
    - Richer name wins, non-empty dose/timing win
    - Low-signal fragments get absorbed into matching parents
    - Deduplicates same-family entries
    """
    merged = parse_structured_list(existing_json)

    for new in new_items:
        new_name = new.get("name", "").strip()
        new_dose = new.get("dose", "").strip()
        new_timing = new.get("timing", "").strip()
        if not new_name:
            continue

        new_family = family_from_text(new_name)
        new_tokens = supp_tokens(new_name)
        handled = False

        # Try to find a match in existing items
        for idx, existing in enumerate(merged):
            ex_name = existing.get("name", "")

            # Exact name match (case-insensitive)
            if ex_name.lower() == new_name.lower():
                if new_dose and not existing.get("dose"):
                    merged[idx]["dose"] = new_dose
                elif new_dose:
                    merged[idx]["dose"] = new_dose  # Update to latest
                if new_timing:
                    merged[idx]["timing"] = new_timing
                handled = True
                break

            # Family match
            ex_family = family_from_text(ex_name)
            if new_family and ex_family and new_family == ex_family:
                # If new item is low-signal ("d3", "omega 3"), merge into existing
                if is_low_signal(new_name):
                    if new_dose and not existing.get("dose"):
                        merged[idx]["dose"] = new_dose
                    if new_timing:
                        merged[idx]["timing"] = new_timing
                    handled = True
                    break
                # If existing is low-signal, replace with richer new item
                if is_low_signal(ex_name):
                    merged[idx]["name"] = new_name
                    if new_dose:
                        merged[idx]["dose"] = new_dose
                    if new_timing:
                        merged[idx]["timing"] = new_timing
                    handled = True
                    break
                # Both are rich — prefer longer/richer name
                if len(new_name) > len(ex_name):
                    merged[idx]["name"] = new_name
                if new_dose:
                    merged[idx]["dose"] = new_dose
                if new_timing:
                    merged[idx]["timing"] = new_timing
                handled = True
                break

            # Token overlap match
            common = new_tokens & supp_tokens(ex_name)
            if len(common) >= 2 or (len(common) == 1 and len(new_tokens) <= 2):
                if is_low_signal(new_name):
                    if new_dose:
                        merged[idx]["dose"] = new_dose
                    if new_timing:
                        merged[idx]["timing"] = new_timing
                else:
                    if len(new_name) > len(ex_name):
                        merged[idx]["name"] = new_name
                    if new_dose:
                        merged[idx]["dose"] = new_dose
                    if new_timing:
                        merged[idx]["timing"] = new_timing
                handled = True
                break

        if not handled:
            if is_low_signal(new_name):
                # Try harder: check family keywords
                if new_family:
                    for idx, existing in enumerate(merged):
                        if family_matches_item(new_family, existing.get("name", "")):
                            if new_dose:
                                merged[idx]["dose"] = new_dose
                            if new_timing:
                                merged[idx]["timing"] = new_timing
                            handled = True
                            break
                if not handled:
                    # Still orphan — expand alias and add
                    alias = SUPP_ALIAS_MAP.get(new_name.lower(), new_name)
                    merged.append(StructuredItem(name=alias, dose=new_dose, timing=new_timing))
            else:
                merged.append(StructuredItem(name=new_name, dose=new_dose, timing=new_timing))

    return json.dumps(merged) if merged else None


# ---------------------------------------------------------------------------
# Migration / cleanup: deduplicate and absorb orphan fragments
# ---------------------------------------------------------------------------

def cleanup_structured_list(raw: str | None) -> str | None:
    """Parse, deduplicate, absorb orphan fragments, return cleaned JSON."""
    items = parse_structured_list(raw)
    if not items:
        return raw

    cleaned: list[StructuredItem] = []
    for item in items:
        name = item.get("name", "").strip()
        dose = item.get("dose", "").strip()
        timing = item.get("timing", "").strip()
        if not name:
            continue

        family = family_from_text(name)
        merged = False

        for idx, existing in enumerate(cleaned):
            ex_family = family_from_text(existing.get("name", ""))

            # Same family → merge
            if family and ex_family and family == ex_family:
                # Keep the richer name
                if len(name) > len(existing.get("name", "")):
                    cleaned[idx]["name"] = name
                if dose and not existing.get("dose"):
                    cleaned[idx]["dose"] = dose
                elif dose and len(dose) > len(existing.get("dose", "")):
                    cleaned[idx]["dose"] = dose
                if timing:
                    cleaned[idx]["timing"] = timing
                merged = True
                break

            # Exact name match
            if existing.get("name", "").lower() == name.lower():
                if dose:
                    cleaned[idx]["dose"] = dose
                if timing:
                    cleaned[idx]["timing"] = timing
                merged = True
                break

        if not merged:
            if is_low_signal(name):
                # Try to absorb into any existing item by family
                if family:
                    for idx, existing in enumerate(cleaned):
                        if family_matches_item(family, existing.get("name", "")):
                            if dose:
                                cleaned[idx]["dose"] = dose
                            if timing:
                                cleaned[idx]["timing"] = timing
                            merged = True
                            break
                if not merged:
                    alias = SUPP_ALIAS_MAP.get(name.lower(), name)
                    cleaned.append(StructuredItem(name=alias, dose=dose, timing=timing))
            else:
                cleaned.append(StructuredItem(name=name, dose=dose, timing=timing))

    new_json = json.dumps(cleaned)
    return new_json if new_json != raw else raw
