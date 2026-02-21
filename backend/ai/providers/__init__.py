from ai.providers.base import AIProvider
from ai.providers.anthropic import AnthropicProvider
from ai.providers.openai_provider import OpenAIProvider
from ai.providers.google import GoogleProvider


def _looks_like_provider_model(provider_name: str, model_id: str | None) -> bool:
    if not model_id:
        return False
    m = model_id.strip().lower()
    if not m:
        return False
    if provider_name == "anthropic":
        return "claude" in m
    if provider_name == "openai":
        return m.startswith("gpt") or m.startswith("o") or "gpt" in m
    if provider_name == "google":
        return "gemini" in m
    return True


def get_provider(
    provider_name: str,
    api_key: str,
    reasoning_model: str | None = None,
    utility_model: str | None = None,
) -> AIProvider:
    providers = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "google": GoogleProvider,
    }
    cls = providers.get(provider_name)
    if not cls:
        raise ValueError(f"Unknown provider: {provider_name}")

    safe_reasoning = reasoning_model if _looks_like_provider_model(provider_name, reasoning_model) else None
    safe_utility = utility_model if _looks_like_provider_model(provider_name, utility_model) else None
    return cls(api_key=api_key, reasoning_model=safe_reasoning, utility_model=safe_utility)
