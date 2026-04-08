"""
Provider-agnostic tool definitions.

Tools are defined once in a neutral format, then converted to
provider-specific schemas at runtime by each provider.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ToolParameterType(Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


@dataclass
class ToolParameter:
    name: str
    type: ToolParameterType
    description: str
    required: bool = True
    enum: Optional[list[str]] = None
    default: Any = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    # If True, the tool runs async and the LLM doesn't wait for the result
    non_blocking: bool = False

    def to_json_schema(self) -> dict:
        """Convert to standard JSON Schema (used by Claude, OpenAI)."""
        properties = {}
        required = []
        for p in self.parameters:
            prop: dict[str, Any] = {
                "type": p.type.value,
                "description": p.description,
            }
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def to_gemini_schema(self) -> dict:
        """Convert to Gemini's function declaration format."""
        type_map = {
            ToolParameterType.STRING: "STRING",
            ToolParameterType.INTEGER: "INTEGER",
            ToolParameterType.NUMBER: "NUMBER",
            ToolParameterType.BOOLEAN: "BOOLEAN",
            ToolParameterType.OBJECT: "OBJECT",
            ToolParameterType.ARRAY: "ARRAY",
        }

        properties = {}
        required = []
        for p in self.parameters:
            prop: dict[str, Any] = {
                "type": type_map[p.type],
                "description": p.description,
            }
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        decl: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "OBJECT",
                "properties": properties,
            },
        }
        if required:
            decl["parameters"]["required"] = required
        return decl

    def to_claude_schema(self) -> dict:
        """Convert to Anthropic Claude's tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.to_json_schema(),
        }


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def unregister(self, name: str):
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def to_gemini_format(self) -> list[dict]:
        """Export all tools in Gemini function_declarations format."""
        declarations = [t.to_gemini_schema() for t in self._tools.values()]
        return [{"function_declarations": declarations}]

    def to_claude_format(self) -> list[dict]:
        """Export all tools in Claude tool format."""
        return [t.to_claude_schema() for t in self._tools.values()]

    def to_json_schema_format(self) -> list[dict]:
        """Export all tools in OpenAI-compatible format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.to_json_schema(),
                },
            }
            for t in self._tools.values()
        ]
