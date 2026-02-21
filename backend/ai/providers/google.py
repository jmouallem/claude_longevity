import base64
import json
from collections.abc import AsyncGenerator

import httpx
from fastapi import HTTPException

from ai.providers.base import AIProvider


class GoogleProvider(AIProvider):
    """Google Gemini AI provider."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    DEFAULT_REASONING_MODEL = "gemini-2.5-pro"
    DEFAULT_UTILITY_MODEL = "gemini-2.0-flash"

    def __init__(
        self,
        api_key: str,
        reasoning_model: str | None = None,
        utility_model: str | None = None,
        deep_thinking_model: str | None = None,
    ):
        super().__init__(api_key, reasoning_model, utility_model, deep_thinking_model)

    def supports_web_search(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _endpoint(self, model: str, stream: bool = False) -> str:
        if stream:
            return f"{self.BASE_URL}/{model}:streamGenerateContent?alt=sse&key={self.api_key}"
        return f"{self.BASE_URL}/{model}:generateContent?key={self.api_key}"

    @staticmethod
    def _convert_messages(messages: list[dict]) -> list[dict]:
        """Convert OpenAI-style messages to Gemini format."""
        contents = []
        for msg in messages:
            role = msg["role"]
            # Gemini uses "user" and "model" roles
            if role == "assistant":
                role = "model"
            text = msg.get("content", "")
            if isinstance(text, str):
                contents.append({
                    "role": role,
                    "parts": [{"text": text}],
                })
            else:
                # Already structured content (e.g. multimodal)
                contents.append({
                    "role": role,
                    "parts": text if isinstance(text, list) else [{"text": str(text)}],
                })
        return contents

    # ------------------------------------------------------------------
    # chat
    # ------------------------------------------------------------------
    async def chat(
        self,
        messages: list[dict],
        model: str,
        system: str = "",
        stream: bool = False,
        tools: list | None = None,
    ) -> dict | AsyncGenerator:
        contents = self._convert_messages(messages)

        payload: dict = {"contents": contents}

        if system:
            payload["system_instruction"] = {
                "parts": [{"text": system}],
            }

        if tools:
            payload["tools"] = tools

        if stream:
            return await self._stream_chat(payload, model)
        return await self._non_stream_chat(payload, model)

    # ---- non-streaming ------------------------------------------------
    async def _non_stream_chat(self, payload: dict, model: str) -> dict:
        url = self._endpoint(model, stream=False)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Google API error: {resp.text}",
                )
            data = resp.json()

        # Extract text from response
        content = ""
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                content += part.get("text", "")

        usage = data.get("usageMetadata", {})
        return {
            "content": content,
            "tokens_in": usage.get("promptTokenCount", 0),
            "tokens_out": usage.get("candidatesTokenCount", 0),
            "model": model,
        }

    # ---- streaming ----------------------------------------------------
    async def _stream_chat(self, payload: dict, model: str) -> AsyncGenerator:
        async def _generator() -> AsyncGenerator:
            tokens_in = 0
            tokens_out = 0
            url = self._endpoint(model, stream=True)

            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise HTTPException(
                            status_code=resp.status_code,
                            detail=f"Google streaming error: {body.decode()}",
                        )

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[len("data: "):]

                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        # Extract text chunks
                        candidates = event.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for part in parts:
                                text = part.get("text", "")
                                if text:
                                    yield {"type": "chunk", "text": text}

                        # Collect usage metadata
                        usage = event.get("usageMetadata", {})
                        if usage:
                            tokens_in = usage.get("promptTokenCount", tokens_in)
                            tokens_out = usage.get("candidatesTokenCount", tokens_out)

            yield {
                "type": "done",
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "model": model,
            }

        return _generator()

    # ------------------------------------------------------------------
    # chat_with_vision
    # ------------------------------------------------------------------
    async def chat_with_vision(
        self,
        messages: list[dict],
        image_bytes: bytes,
        model: str,
        system: str = "",
    ) -> dict:
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Detect MIME type
        mime_type = "image/png"
        if image_bytes[:3] == b"\xff\xd8\xff":
            mime_type = "image/jpeg"
        elif image_bytes[:4] == b"RIFF":
            mime_type = "image/webp"

        image_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": b64,
            }
        }

        # Build contents with image in last user message
        contents = []
        for msg in messages:
            role = msg["role"]
            if role == "assistant":
                role = "model"
            text = msg.get("content", "")
            if msg["role"] == "user" and isinstance(text, str):
                contents.append({
                    "role": role,
                    "parts": [image_part, {"text": text}],
                })
            else:
                contents.append({
                    "role": role,
                    "parts": [{"text": text if isinstance(text, str) else str(text)}],
                })

        payload: dict = {"contents": contents}
        if system:
            payload["system_instruction"] = {
                "parts": [{"text": system}],
            }

        return await self._non_stream_chat(payload, model)

    # ------------------------------------------------------------------
    # validate_key
    # ------------------------------------------------------------------
    async def validate_key(self) -> bool:
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": "Hi"}]},
            ],
        }
        url = self._endpoint(self.get_utility_model(), stream=False)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=401,
                    detail=f"Google key validation failed: {resp.text}",
                )
        return True
