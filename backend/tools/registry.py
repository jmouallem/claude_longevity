from __future__ import annotations

from typing import Any

from tools.base import ToolContext, ToolExecutionError, ToolHandler, ToolSpec


class ToolRegistry:
    def __init__(self):
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def list_specs(self) -> list[ToolSpec]:
        return sorted(self._specs.values(), key=lambda s: s.name)

    def get_spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def execute(self, name: str, args: dict[str, Any] | None, ctx: ToolContext) -> dict[str, Any]:
        spec = self._specs.get(name)
        handler = self._handlers.get(name)
        if not spec or not handler:
            raise ToolExecutionError(f"Unknown tool: {name}")

        if spec.allowed_specialists is not None:
            if ctx.specialist_id not in spec.allowed_specialists:
                raise ToolExecutionError(
                    f"Specialist `{ctx.specialist_id}` is not allowed to execute `{name}`"
                )

        payload = args or {}
        if not isinstance(payload, dict):
            raise ToolExecutionError("Tool arguments must be a JSON object")

        for key in spec.required_fields:
            if key not in payload:
                raise ToolExecutionError(f"Missing required field: `{key}`")

        if spec.validator is not None:
            spec.validator(payload)

        return handler(payload, ctx)
