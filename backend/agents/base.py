"""
Base agent interface.

Every capability in INARA (CAD, printer, web, Kasa, etc.) is an agent
that implements this interface. Agents register their tools and handle
execution when those tools are called by the LLM.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from llm.tools import Tool


@dataclass
class AgentResult:
    """Standardized result from agent execution."""
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    # For non-blocking agents: the result will be delivered via event bus
    is_async: bool = False


class BaseAgent(ABC):
    """Abstract base for all INARA agents (plugins)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique agent identifier (e.g. 'cad', 'printer', 'kasa')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        ...

    @abstractmethod
    def get_tools(self) -> list[Tool]:
        """Return the tools this agent provides.

        These are registered in the central ToolRegistry and made
        available to the LLM.
        """
        ...

    @abstractmethod
    async def handle_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        **context,
    ) -> AgentResult:
        """Execute a tool call.

        Args:
            tool_name: The name of the tool being called.
            args: The arguments passed by the LLM.
            **context: Additional context (project_path, etc.)

        Returns:
            AgentResult with the outcome.
        """
        ...

    async def initialize(self):
        """Called once when the agent is loaded. Override for setup logic."""
        pass

    async def shutdown(self):
        """Called when the agent is being unloaded. Override for cleanup."""
        pass
