from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class AIProvider(ABC):
    """Abstract base class for all AI providers."""

    def __init__(
        self,
        api_key: str,
        reasoning_model: str | None = None,
        utility_model: str | None = None,
    ):
        self.api_key = api_key
        self._reasoning_model = reasoning_model
        self._utility_model = utility_model

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        system: str = "",
        stream: bool = False,
        tools: list | None = None,
    ) -> dict | AsyncGenerator:
        """Send a chat request to the provider.

        Args:
            messages: List of message dicts with role and content.
            model: Model identifier to use.
            system: Optional system prompt.
            stream: If True, return an async generator yielding chunk dicts.
            tools: Optional list of tool definitions.

        Returns:
            If stream=False: dict with content, tokens_in, tokens_out, model.
            If stream=True: AsyncGenerator yielding dicts.
        """
        ...

    @abstractmethod
    async def chat_with_vision(
        self,
        messages: list[dict],
        image_bytes: bytes,
        model: str,
        system: str = "",
    ) -> dict:
        """Send a chat request that includes an image.

        Args:
            messages: List of message dicts with role and content.
            image_bytes: Raw image bytes.
            model: Model identifier to use.
            system: Optional system prompt.

        Returns:
            dict with content, tokens_in, tokens_out, model.
        """
        ...

    @abstractmethod
    async def validate_key(self) -> bool:
        """Validate the API key by making a lightweight test request.

        Returns:
            True if the key is valid.

        Raises:
            Exception if validation fails.
        """
        ...

    def get_reasoning_model(self) -> str:
        """Return the reasoning (higher-capability) model identifier."""
        return self._reasoning_model or self.DEFAULT_REASONING_MODEL

    def get_utility_model(self) -> str:
        """Return the utility (faster/cheaper) model identifier."""
        return self._utility_model or self.DEFAULT_UTILITY_MODEL

    def supports_web_search(self) -> bool:
        """Whether this provider supports web search tools."""
        return False
