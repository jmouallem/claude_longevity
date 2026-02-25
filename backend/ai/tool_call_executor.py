"""Post-response tool call extraction and execution.

Option C implementation: the AI emits ``<tool_call>`` blocks in its text
response.  After streaming completes a post-processor extracts the blocks,
validates them, and executes each via the existing ``tool_registry``.

The module is designed around a ``ToolCallExecutor`` protocol so the
concrete implementation can be swapped from *DirectToolCallExecutor*
(Option C — inline extraction) to an *AgentToolCallExecutor* (Option B —
delegate to a sub-agent or microservice) without changing the orchestrator
call-site.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from tools.base import ToolContext, ToolExecutionError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRequest:
    """A single tool call request parsed from the AI response."""
    tool: str
    args: dict[str, Any]
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class ToolCallResult:
    """Result of executing a single tool call."""
    call_id: str
    tool: str
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Protocol (swap-point for Option B migration)
# ---------------------------------------------------------------------------

@runtime_checkable
class ToolCallExecutor(Protocol):
    """Abstract executor interface.

    Option C: ``DirectToolCallExecutor`` — calls ``tool_registry.execute()``
    directly in the same process.

    Option B (future): ``AgentToolCallExecutor`` — delegates to a sub-agent,
    microservice, or secondary model for validation and execution.
    """

    async def execute(
        self,
        requests: list[ToolCallRequest],
        ctx: ToolContext,
    ) -> list[ToolCallResult]:
        ...


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.DOTALL,
)

# Tools the AI is allowed to call.  Keep this list small and intentional.
AI_CALLABLE_TOOLS: frozenset[str] = frozenset({
    "plan_task_update_status",
    "create_goal",
    "update_goal",
})


def extract_tool_calls(text: str) -> list[ToolCallRequest]:
    """Extract ``<tool_call>`` blocks from AI response text.

    Each block must contain valid JSON with at least a ``"tool"`` key.
    Invalid or disallowed blocks are logged and skipped.
    """
    requests: list[ToolCallRequest] = []
    for match in _TOOL_CALL_RE.finditer(text):
        raw = match.group(1).strip()
        # Handle markdown code fences inside the block
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Skipping malformed <tool_call> block: %s", exc)
            continue
        if not isinstance(parsed, dict):
            logger.warning("Skipping non-dict <tool_call> block")
            continue
        tool_name = str(parsed.get("tool") or parsed.get("name") or "").strip()
        if not tool_name:
            logger.warning("Skipping <tool_call> with no tool name")
            continue
        if tool_name not in AI_CALLABLE_TOOLS:
            logger.warning("AI tried to call disallowed tool: %s", tool_name)
            continue
        args = parsed.get("args") or parsed.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        requests.append(ToolCallRequest(tool=tool_name, args=args))
    return requests


def strip_tool_calls(text: str) -> str:
    """Remove ``<tool_call>...</tool_call>`` blocks from display text.

    Removes the blocks and any surrounding blank-line padding so the user
    sees clean prose without JSON artifacts.
    """
    # Remove blocks (including surrounding whitespace/newlines)
    cleaned = _TOOL_CALL_RE.sub("", text)
    # Collapse runs of 3+ newlines to 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Option C: Direct executor (calls tool_registry in-process)
# ---------------------------------------------------------------------------

class DirectToolCallExecutor:
    """Execute tool calls directly via the in-process tool registry.

    This is the Option C implementation.  To migrate to Option B, replace
    this class with an ``AgentToolCallExecutor`` that delegates to a
    sub-agent or remote service while keeping the same interface.
    """

    def __init__(self, registry):
        """Accept a ``ToolRegistry`` instance."""
        self._registry = registry

    async def execute(
        self,
        requests: list[ToolCallRequest],
        ctx: ToolContext,
    ) -> list[ToolCallResult]:
        results: list[ToolCallResult] = []
        for req in requests:
            try:
                out = self._registry.execute(req.tool, req.args, ctx)
                results.append(ToolCallResult(
                    call_id=req.call_id,
                    tool=req.tool,
                    success=True,
                    result=out,
                ))
                logger.info("AI tool call succeeded: %s (id=%s)", req.tool, req.call_id)
            except ToolExecutionError as exc:
                results.append(ToolCallResult(
                    call_id=req.call_id,
                    tool=req.tool,
                    success=False,
                    error=str(exc),
                ))
                logger.warning("AI tool call failed: %s — %s", req.tool, exc)
            except Exception as exc:
                results.append(ToolCallResult(
                    call_id=req.call_id,
                    tool=req.tool,
                    success=False,
                    error=str(exc),
                ))
                logger.error("AI tool call unexpected error: %s — %s", req.tool, exc)
        return results


def format_tool_results_context(results: list[ToolCallResult]) -> str:
    """Build a human-readable summary of tool execution results.

    This is appended to the assistant response so the user can see
    what actions were taken.
    """
    if not results:
        return ""
    lines: list[str] = []
    for r in results:
        if r.success:
            detail = ""
            if r.result:
                if "status" in r.result:
                    detail = f" -> {r.result['status']}"
                elif "goal" in r.result:
                    goal = r.result["goal"]
                    detail = f" -> {goal.get('title', 'goal')} ({goal.get('status', '')})"
            lines.append(f"  - {r.tool}: done{detail}")
        else:
            lines.append(f"  - {r.tool}: failed - {r.error}")
    return "\n".join(lines)
