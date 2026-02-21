from tools.registry import ToolRegistry
from tools.health_tools import register_health_tools
from tools.time_tools import register_time_tools
from tools.write_tools import register_write_tools
from tools.web_tools import register_web_tools

tool_registry = ToolRegistry()
register_health_tools(tool_registry)
register_time_tools(tool_registry)
register_write_tools(tool_registry)
register_web_tools(tool_registry)

__all__ = ["tool_registry", "ToolRegistry"]
