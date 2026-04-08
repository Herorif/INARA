"""
CAD Agent — generates and iterates on 3D models using build123d.

Refactored to use the LLM abstraction layer instead of direct Gemini calls.
Deduplicated generate/iterate into a single code generation pipeline.
"""

import asyncio
import base64
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Optional

from agents.base import AgentResult, BaseAgent
from core.event_bus import Event, Events, EventBus
from llm.base import BaseLLMProvider, LLMResponse, Message, MessageRole
from llm.tools import Tool, ToolParameter, ToolParameterType

SYSTEM_INSTRUCTION = """
You are a Python-based 3D CAD Engineer using the `build123d` library.
Your goal is to write a Python script that generates a 3D model based on the user's request.

Requirements:
1. Start with `from build123d import *`.
2. Include `import numpy as np` if you use any numpy functions (like `np.sign`, `np.pi`).
3. You MUST assign the final object to a variable named `result_part`.
4. If you create a sketch or line, extrude it to make it a solid `Part`.
5. The model should be centered at (0,0,0) and have reasonable dimensions (mm).
6. **IMPORTANT**: Do NOT use old or PascalCase function names for core operations.
   - Use `make_face()` instead of `MakeFace()`.
   - Use `extrude()` instead of `Extrude()`.
   - Use `fillet()` instead of `Fillet()`.
   - Use `chamfer()` instead of `Chamfer()`.
   - Use `revolve()` instead of `Revolve()`.
   - Use `loft()` instead of `Loft()`.
   - Use `sweep()` instead of `Sweep()`.
   - Use `offset()` instead of `Offset()`.
   - generally prefer lowercase builder methods inside contexts.

7. **Vector Access**: Do NOT access vector components like `v.X`, `v.Y`, `v.Z` unless you are sure they exist (use `v.X` etc on Vector objects, but ensure they are Vectors).
8. **Final Output**: The script MUST end by exporting the final part to an STL file named 'output.stl'.
   - `export_stl(result_part, 'output.stl')`

9. **Robustness**: Operations like `fillet()` and `chamfer()` will crash if the radius is too large for the geometry.
   - Use conservative values (e.g., 0.5mm to 2mm) unless you are certain of the dimensions.
   - If a fillet is purely aesthetic, keep it small to ensure success.

Example Script:
```python
from build123d import *

with BuildPart() as p:
    Box(10, 10, 10)
    Fillet(p.edges(), radius=1)

result_part = p.part
export_stl(result_part, 'output.stl')
```
"""

MAX_RETRIES = 3


class CadAgent(BaseAgent):
    def __init__(self, llm: BaseLLMProvider, event_bus: EventBus):
        self._llm = llm
        self._bus = event_bus

    @property
    def name(self) -> str:
        return "cad"

    @property
    def description(self) -> str:
        return "Generates and iterates on 3D CAD models using build123d"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="generate_cad",
                description="Generates a 3D CAD model based on a prompt.",
                parameters=[ToolParameter("prompt", ToolParameterType.STRING, "The description of the object to generate.")],
                non_blocking=True,
            ),
            Tool(
                name="iterate_cad",
                description="Modifies or iterates on the current CAD design based on user feedback.",
                parameters=[ToolParameter("prompt", ToolParameterType.STRING, "The changes to apply to the current design.")],
                non_blocking=True,
            ),
        ]

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        prompt = args.get("prompt", "")
        output_dir = context.get("output_dir")

        if tool_name == "generate_cad":
            result = await self._generate(prompt, output_dir)
        elif tool_name == "iterate_cad":
            result = await self._iterate(prompt, output_dir)
        else:
            return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

        if result:
            self._bus.emit_nowait(Event(
                type=Events.CAD_RESULT,
                data=result,
                source=self.name,
            ))
            return AgentResult(success=True, data=result, is_async=True)
        return AgentResult(success=False, message="CAD generation failed after all retries")

    async def _generate(self, prompt: str, output_dir: Optional[str] = None) -> Optional[dict]:
        """Generate a new CAD model from scratch."""
        initial_prompt = (
            f"You are a build123d expert. Write a generic python script to create "
            f"a 3D model of: {prompt}. Ensure you export to 'output.stl'. Unscaled."
        )
        return await self._run_code_gen_loop(initial_prompt, prompt, output_dir)

    async def _iterate(self, prompt: str, output_dir: Optional[str] = None) -> Optional[dict]:
        """Iterate on an existing CAD design."""
        work_dir = output_dir or self._default_work_dir()
        script_path = os.path.join(work_dir, "current_design.py")

        if not os.path.exists(script_path):
            # No existing design — fall back to fresh generation
            return await self._generate(prompt, output_dir)

        with open(script_path, "r") as f:
            existing_code = f.read()

        # Sanitize paths in existing code to prevent LLM confusion
        existing_code = re.sub(
            r"['\"]C:\\\\?Users\\\\?[^'\"]+\\\\?output[^'\"]*\.stl['\"]",
            "'output.stl'",
            existing_code,
        )
        existing_code = re.sub(
            r"['\"]C:/Users/[^'\"]+/output[^'\"]*\.stl['\"]",
            "'output.stl'",
            existing_code,
        )

        initial_prompt = f"""
You are iterating on an existing 3D model script.

Current Python Code:
```python
{existing_code}
```

User Request: {prompt}

Task: Rewrite the code to satisfy the user's request while maintaining the rest of the model structure.
Ensure you still export to 'output.stl'.
"""
        return await self._run_code_gen_loop(initial_prompt, prompt, output_dir)

    async def _run_code_gen_loop(
        self,
        initial_prompt: str,
        user_prompt: str,
        output_dir: Optional[str] = None,
    ) -> Optional[dict]:
        """Core code generation loop with retry logic. Used by both generate and iterate."""
        work_dir = output_dir or self._default_work_dir()
        os.makedirs(work_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_stl = os.path.join(work_dir, f"output_{timestamp}.stl")
        script_path = os.path.join(work_dir, "current_design.py")

        current_prompt = initial_prompt

        for attempt in range(MAX_RETRIES):
            # Emit status
            self._bus.emit_nowait(Event(
                type=Events.CAD_STATUS,
                data={
                    "status": "generating" if attempt == 0 else "retrying",
                    "attempt": attempt + 1,
                    "max_attempts": MAX_RETRIES,
                    "error": None,
                },
                source=self.name,
            ))

            # Ask LLM for code (streaming for thought updates)
            raw_content = ""
            messages = [Message(role=MessageRole.USER, content=current_prompt)]

            async for chunk in self._llm.stream(
                messages=messages,
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=1.0,
                thinking=True,
            ):
                if chunk.thinking:
                    self._bus.emit_nowait(Event(
                        type=Events.CAD_THOUGHT,
                        data={"text": chunk.thinking},
                        source=self.name,
                    ))
                if chunk.text:
                    raw_content += chunk.text

            if not raw_content:
                continue

            # Extract code block
            code = self._extract_code(raw_content)
            if code is None:
                continue

            # Write script with correct output path
            safe_output_path = output_stl.replace("\\", "\\\\")
            code_with_path = code.replace("output.stl", safe_output_path)
            with open(script_path, "w") as f:
                f.write(code_with_path)

            # Execute
            success, stdout, stderr = await self._execute_script(script_path)

            if not success:
                short_error = stderr.strip().split("\n")[-1][:100] if stderr.strip() else "Unknown error"
                self._bus.emit_nowait(Event(
                    type=Events.CAD_STATUS,
                    data={
                        "status": "retrying",
                        "attempt": attempt + 1,
                        "max_attempts": MAX_RETRIES,
                        "error": short_error,
                    },
                    source=self.name,
                ))
                current_prompt = (
                    f"The Python script you generated failed with this error:\n{stderr}\n\n"
                    f"Please fix the code. Return the full corrected script.\n"
                    f"Ensure you still export to 'output.stl'.\n"
                    f"Original request: {user_prompt}"
                )
                continue

            # Check output
            if os.path.exists(output_stl):
                with open(output_stl, "rb") as f:
                    stl_data = f.read()
                return {
                    "format": "stl",
                    "data": base64.b64encode(stl_data).decode("utf-8"),
                    "file_path": output_stl,
                }
            else:
                current_prompt = (
                    "The script executed successfully but 'output.stl' was not found. "
                    "Ensure you call `export_stl(result_part, 'output.stl')` at the end."
                )
                continue

        # All retries failed
        self._bus.emit_nowait(Event(
            type=Events.CAD_STATUS,
            data={
                "status": "failed",
                "attempt": MAX_RETRIES,
                "max_attempts": MAX_RETRIES,
                "error": "All generation attempts failed",
            },
            source=self.name,
        ))
        return None

    @staticmethod
    def _extract_code(raw_content: str) -> Optional[str]:
        """Extract Python code from LLM response."""
        code_match = re.search(r"```python(.*?)```", raw_content, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()
        # Fallback: check if it looks like code
        if "import build123d" in raw_content or "from build123d" in raw_content:
            return raw_content
        return None

    @staticmethod
    async def _execute_script(script_path: str) -> tuple[bool, str, str]:
        """Run a Python script and return (success, stdout, stderr)."""
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, script_path],
                capture_output=True,
                text=True,
            )
            return proc.returncode == 0, proc.stdout, proc.stderr
        except Exception as e:
            return False, "", str(e)

    @staticmethod
    def _default_work_dir() -> str:
        import tempfile
        return tempfile.gettempdir()
