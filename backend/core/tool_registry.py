"""
Central tool registry for INARA.

All agent tools are registered here. The registry converts them
to whatever format the active LLM provider needs.
"""

from llm.tools import Tool, ToolParameter, ToolParameterType, ToolRegistry


def create_default_registry() -> ToolRegistry:
    """Create and populate the default INARA tool registry."""
    registry = ToolRegistry()

    # --- CAD ---
    registry.register(Tool(
        name="generate_cad",
        description="Generates a 3D CAD model based on a prompt.",
        parameters=[
            ToolParameter("prompt", ToolParameterType.STRING, "The description of the object to generate."),
        ],
        non_blocking=True,
    ))
    registry.register(Tool(
        name="iterate_cad",
        description=(
            "Modifies or iterates on the current CAD design based on user feedback. "
            "Use this when the user asks to adjust, change, modify, or iterate on "
            "the existing 3D model (e.g., 'make it taller', 'add a handle')."
        ),
        parameters=[
            ToolParameter("prompt", ToolParameterType.STRING, "The changes or modifications to apply to the current design."),
        ],
        non_blocking=True,
    ))

    # --- Web Agent ---
    registry.register(Tool(
        name="run_web_agent",
        description="Opens a web browser and performs a task according to the prompt.",
        parameters=[
            ToolParameter("prompt", ToolParameterType.STRING, "The detailed instructions for the web browser agent."),
        ],
        non_blocking=True,
    ))

    # --- File Operations ---
    registry.register(Tool(
        name="write_file",
        description="Writes content to a file at the specified path. Overwrites if exists.",
        parameters=[
            ToolParameter("path", ToolParameterType.STRING, "The path of the file to write to."),
            ToolParameter("content", ToolParameterType.STRING, "The content to write to the file."),
        ],
    ))
    registry.register(Tool(
        name="read_directory",
        description="Lists the contents of a directory.",
        parameters=[
            ToolParameter("path", ToolParameterType.STRING, "The path of the directory to list."),
        ],
    ))
    registry.register(Tool(
        name="read_file",
        description="Reads the content of a file.",
        parameters=[
            ToolParameter("path", ToolParameterType.STRING, "The path of the file to read."),
        ],
    ))

    # --- Projects ---
    registry.register(Tool(
        name="create_project",
        description="Creates a new project folder to organize files.",
        parameters=[
            ToolParameter("name", ToolParameterType.STRING, "The name of the new project."),
        ],
    ))
    registry.register(Tool(
        name="switch_project",
        description="Switches the current active project context.",
        parameters=[
            ToolParameter("name", ToolParameterType.STRING, "The name of the project to switch to."),
        ],
    ))
    registry.register(Tool(
        name="list_projects",
        description="Lists all available projects.",
        parameters=[],
    ))

    # --- Smart Home ---
    registry.register(Tool(
        name="list_smart_devices",
        description="Lists all available smart home devices (lights, plugs, etc.) on the network.",
        parameters=[],
    ))
    registry.register(Tool(
        name="control_light",
        description="Controls a smart light device.",
        parameters=[
            ToolParameter("target", ToolParameterType.STRING, "The IP address of the device to control. Prefer IP over alias."),
            ToolParameter("action", ToolParameterType.STRING, "The action: 'turn_on', 'turn_off', or 'set'."),
            ToolParameter("brightness", ToolParameterType.INTEGER, "Optional brightness level (0-100).", required=False),
            ToolParameter("color", ToolParameterType.STRING, "Optional color name (e.g., 'red', 'cool white') or 'warm'.", required=False),
        ],
    ))

    # --- 3D Printing ---
    registry.register(Tool(
        name="discover_printers",
        description="Discovers 3D printers available on the local network.",
        parameters=[],
    ))
    registry.register(Tool(
        name="print_stl",
        description="Prints an STL file to a 3D printer. Handles slicing and uploading.",
        parameters=[
            ToolParameter("stl_path", ToolParameterType.STRING, "Path to STL file, or 'current' for the most recent CAD model."),
            ToolParameter("printer", ToolParameterType.STRING, "Printer name or IP address."),
            ToolParameter("profile", ToolParameterType.STRING, "Optional slicer profile name.", required=False),
        ],
    ))
    registry.register(Tool(
        name="get_print_status",
        description="Gets the current status of a 3D printer including progress, time remaining, and temperatures.",
        parameters=[
            ToolParameter("printer", ToolParameterType.STRING, "Printer name or IP address."),
        ],
    ))

    return registry
