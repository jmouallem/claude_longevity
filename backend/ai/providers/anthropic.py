import base64
import json
from collections.abc import AsyncGenerator

import httpx
from fastapi import HTTPException

from ai.providers.base import AIProvider


class AnthropicProvider(AIProvider):
    """Anthropic / Claude AI provider."""

    BASE_URL = "https://api.anthropic.com/v1/messages"
    DEFAULT_REASONING_MODEL = "claude-sonnet-4-20250514"
    DEFAULT_UTILITY_MODEL = "claude-haiku-4-5-20251001"

    def __init__(
        self,
        api_key: str,
        reasoning_model: str | None = None,
        utility_model: str | None = None,
        deep_thinking_model: str | None = None,
    ):
        super().__init__(api_key, reasoning_model, utility_model, deep_thinking_model)
        self._headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def supports_web_search(self) -> bool:
        return True

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
        payload: dict = {
            "model": model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
            return await self._stream_chat(payload)
        return await self._non_stream_chat(payload)

    # ---- non-streaming ------------------------------------------------
    async def _non_stream_chat(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                self.BASE_URL,
                headers=self._headers,
                json=payload,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Anthropic API error: {resp.text}",
                )
            data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block["text"]

        usage = data.get("usage", {})
        return {
            "content": content,
            "tokens_in": usage.get("input_tokens", 0),
            "tokens_out": usage.get("output_tokens", 0),
            "model": data.get("model", payload["model"]),
        }

    # ---- streaming ----------------------------------------------------
    async def _stream_chat(self, payload: dict) -> AsyncGenerator:
        async def _generator() -> AsyncGenerator:
            tokens_in = 0
            tokens_out = 0
            model_name = payload["model"]

            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    self.BASE_URL,
                    headers=self._headers,
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise HTTPException(
                            status_code=resp.status_code,
                            detail=f"Anthropic streaming error: {body.decode()}",
                        )

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[len("data: "):]
                        if raw.strip() == "[DONE]":
                            break

                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type")

                        if event_type == "message_start":
                            msg = event.get("message", {})
                            usage = msg.get("usage", {})
                            tokens_in += usage.get("input_tokens", 0)
                            model_name = msg.get("model", model_name)

                        elif event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield {"type": "chunk", "text": text}

                        elif event_type == "message_delta":
                            usage = event.get("usage", {})
                            tokens_out += usage.get("output_tokens", 0)

            yield {
                "type": "done",
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "model": model_name,
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

        # Detect media type (default to png)
        media_type = "image/png"
        if image_bytes[:3] == b"\xff\xd8\xff":
            media_type = "image/jpeg"
        elif image_bytes[:4] == b"RIFF":
            media_type = "image/webp"
        elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            media_type = "image/png"

        image_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64,
            },
        }

        # Append image block to the last user message's content
        vision_messages = []
        for msg in messages:
            if msg["role"] == "user":
                text_content = msg.get("content", "")
                if isinstance(text_content, str):
                    vision_messages.append({
                        "role": "user",
                        "content": [
                            image_block,
                            {"type": "text", "text": text_content},
                        ],
                    })
                else:
                    vision_messages.append(msg)
            else:
                vision_messages.append(msg)

        payload: dict = {
            "model": model,
            "max_tokens": 4096,
            "messages": vision_messages,
        }
        if system:
            payload["system"] = system

        return await self._non_stream_chat(payload)

    # ------------------------------------------------------------------
    # validate_key
    # ------------------------------------------------------------------
    async def validate_key(self) -> bool:
        payload = {
            "model": self.get_utility_model(),
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "Hi"}],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.BASE_URL,
                headers=self._headers,
                json=payload,
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=401,
                    detail=f"Anthropic key validation failed: {resp.text}",
                )
        return True
