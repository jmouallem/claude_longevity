import logging

logger = logging.getLogger(__name__)

IMAGE_ANALYSIS_PROMPT = """Analyze this image in the context of health/nutrition tracking.
Identify what is shown and extract relevant data:
- If nutrition label: extract calories, protein, carbs, fat, sodium, serving size
- If food photo: identify foods, estimate portions and macros
- If BP monitor: extract systolic, diastolic, heart rate
- If supplement bottle: extract name, dose, ingredients
- If scale: extract weight reading
- If other health-related: describe what you see

Return a JSON object with:
{
    "type": "nutrition_label" | "food_photo" | "bp_reading" | "supplement" | "scale" | "other",
    "description": "natural language description of what you see",
    "data": { ... extracted structured data relevant to the type ... }
}"""


async def analyze_image(provider, image_bytes: bytes, hint: str = "") -> dict:
    """Send image to vision-capable model for analysis."""
    prompt = IMAGE_ANALYSIS_PROMPT
    if hint:
        prompt += f"\n\nUser context: {hint}"

    try:
        result = await provider.chat_with_vision(
            messages=[{"role": "user", "content": prompt}],
            image_bytes=image_bytes,
            model=provider.get_reasoning_model(),
        )
        return {"success": True, "content": result["content"]}
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        return {"success": False, "content": f"Image analysis failed: {str(e)}"}
