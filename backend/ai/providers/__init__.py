from ai.providers.base import AIProvider
from ai.providers.anthropic import AnthropicProvider
from ai.providers.openai_provider import OpenAIProvider
from ai.providers.google import GoogleProvider


def get_provider(provider_name: str, api_key: str) -> AIProvider:
    providers = {
        "anthropic": AnthropicProvider,
        "openai": OpenAIProvider,
        "google": GoogleProvider,
    }
    cls = providers.get(provider_name)
    if not cls:
        raise ValueError(f"Unknown provider: {provider_name}")
    return cls(api_key=api_key)
