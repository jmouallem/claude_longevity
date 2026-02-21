import base64
import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import HTTPException

from ai.providers.base import AIProvider


class OpenAIProvider(AIProvider):
    """OpenAI / GPT AI provider."""

    BASE_URL = "https://api.openai.com/v1/chat/completions"
    DEFAULT_REASONING_MODEL = "gpt-4o"
    DEFAULT_UTILITY_MODEL = "gpt-4o-mini"
    DEFAULT_MAX_COMPLETION_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        reasoning_model: str | None = None,
        utility_model: str | None = None,
        deep_thinking_model: str | None = None,
    ):
        super().__init__(api_key, reasoning_model, utility_model, deep_thinking_model)
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

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
        # Prepend system message if provided
        full_messages = list(messages)
        if system:
            full_messages.insert(0, {"role": "system", "content": system})

        payload: dict[str, Any] = {
            "model": model,
            "messages": full_messages,
        }
        payload.update(self._token_limit_field(model, self.DEFAULT_MAX_COMPLETION_TOKENS))
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
            return await self._stream_chat(payload)
        return await self._non_stream_chat(payload)

    # ---- non-streaming ------------------------------------------------
    async def _non_stream_chat(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(self.BASE_URL, headers=self._headers, json=payload)
            if resp.status_code != 200 and self._should_retry_with_alt_token_field(resp):
                resp = await client.post(
                    self.BASE_URL,
                    headers=self._headers,
                    json=self._swap_token_limit_field(payload),
                )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"OpenAI API error: {resp.text}",
                )
            data = resp.json()

        choice = data.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        usage = data.get("usage", {})

        return {
            "content": content,
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
            "model": data.get("model", payload["model"]),
        }

    # ---- streaming ----------------------------------------------------
    async def _stream_chat(self, payload: dict) -> AsyncGenerator:
        async def _generator() -> AsyncGenerator:
            tokens_in = 0
            tokens_out = 0
            model_name = payload["model"]
            active_payload = payload

            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    self.BASE_URL,
                    headers=self._headers,
                    json=active_payload,
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        body_text = body.decode()
                        if self._should_retry_with_alt_token_field(resp, body_text):
                            active_payload = self._swap_token_limit_field(active_payload)
                            async with client.stream(
                                "POST",
                                self.BASE_URL,
                                headers=self._headers,
                                json=active_payload,
                            ) as retry_resp:
                                if retry_resp.status_code != 200:
                                    retry_body = await retry_resp.aread()
                                    raise HTTPException(
                                        status_code=retry_resp.status_code,
                                        detail=f"OpenAI streaming error: {retry_body.decode()}",
                                    )
                                async for line in retry_resp.aiter_lines():
                                    if not line.startswith("data: "):
                                        continue
                                    raw = line[len("data: "):]
                                    if raw.strip() == "[DONE]":
                                        break

                                    try:
                                        event = json.loads(raw)
                                    except json.JSONDecodeError:
                                        continue

                                    model_name = event.get("model", model_name)
                                    usage = event.get("usage")
                                    if usage:
                                        tokens_in = usage.get("prompt_tokens", tokens_in)
                                        tokens_out = usage.get("completion_tokens", tokens_out)

                                    choices = event.get("choices", [])
                                    if not choices:
                                        continue

                                    delta = choices[0].get("delta", {})
                                    text = delta.get("content", "")
                                    if text:
                                        yield {"type": "chunk", "text": text}
                        else:
                            raise HTTPException(
                                status_code=resp.status_code,
                                detail=f"OpenAI streaming error: {body_text}",
                            )
                        # retry branch handled stream output
                        yield {
                            "type": "done",
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "model": model_name,
                        }
                        return

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

                        model_name = event.get("model", model_name)

                        # Collect usage if present (some models return it)
                        usage = event.get("usage")
                        if usage:
                            tokens_in = usage.get("prompt_tokens", tokens_in)
                            tokens_out = usage.get("completion_tokens", tokens_out)

                        choices = event.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield {"type": "chunk", "text": text}

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

        # Detect media type
        media_type = "image/png"
        if image_bytes[:3] == b"\xff\xd8\xff":
            media_type = "image/jpeg"
        elif image_bytes[:4] == b"RIFF":
            media_type = "image/webp"

        data_url = f"data:{media_type};base64,{b64}"

        # Build vision messages — convert last user message to multimodal
        vision_messages = []
        if system:
            vision_messages.append({"role": "system", "content": system})

        for msg in messages:
            if msg["role"] == "user":
                text_content = msg.get("content", "")
                if isinstance(text_content, str):
                    vision_messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                            {"type": "text", "text": text_content},
                        ],
                    })
                else:
                    vision_messages.append(msg)
            else:
                vision_messages.append(msg)

        payload: dict = {
            "model": model,
            "messages": vision_messages,
        }

        return await self._non_stream_chat(payload)

    # ------------------------------------------------------------------
    # validate_key
    # ------------------------------------------------------------------
    async def validate_key(self) -> bool:
        payload: dict[str, Any] = {
            "model": self.get_utility_model(),
            "messages": [{"role": "user", "content": "Hi"}],
        }
        payload.update(self._token_limit_field(self.get_utility_model(), 10))
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.BASE_URL,
                headers=self._headers,
                json=payload,
            )
            if resp.status_code != 200 and self._should_retry_with_alt_token_field(resp):
                resp = await client.post(
                    self.BASE_URL,
                    headers=self._headers,
                    json=self._swap_token_limit_field(payload),
                )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=401,
                    detail=f"OpenAI key validation failed: {resp.text}",
                )
        return True

    def _token_limit_field(self, model: str, limit: int) -> dict[str, int]:
        m = (model or "").strip().lower()
        if m.startswith("o") or m.startswith("gpt-5") or m.startswith("gpt-4.1"):
            return {"max_completion_tokens": limit}
        return {"max_tokens": limit}

    def _swap_token_limit_field(self, payload: dict[str, Any]) -> dict[str, Any]:
        swapped = dict(payload)
        if "max_tokens" in swapped:
            value = swapped.pop("max_tokens")
            swapped["max_completion_tokens"] = value
            return swapped
        if "max_completion_tokens" in swapped:
            value = swapped.pop("max_completion_tokens")
            swapped["max_tokens"] = value
        return swapped

    def _should_retry_with_alt_token_field(self, resp: httpx.Response, body_text: str | None = None) -> bool:
        if resp.status_code != 400:
            return False
        text = (body_text or resp.text or "").lower()
        unsupported_param = "unsupported parameter" in text
        mentions_max_tokens = "max_tokens" in text or "max_completion_tokens" in text
        return unsupported_param and mentions_max_tokens
