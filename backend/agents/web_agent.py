"""
Web Agent  - autonomous browser automation using Playwright.

Refactored to use the LLM abstraction layer. The Playwright browser
automation logic is preserved; only the LLM interaction is swapped.
"""

import asyncio
import base64
from typing import Any, Optional

from playwright.async_api import async_playwright

from agents.base import AgentResult, BaseAgent
from core.event_bus import Event, Events, EventBus
from llm.base import BaseLLMProvider, Message, MessageRole
from llm.tools import Tool, ToolParameter, ToolParameterType

SCREEN_WIDTH = 1440
SCREEN_HEIGHT = 900
MAX_TURNS = 20


class WebAgent(BaseAgent):
    def __init__(self, llm: BaseLLMProvider, event_bus: EventBus):
        self._llm = llm
        self._bus = event_bus
        self.browser = None
        self.context = None
        self.page = None

    @property
    def name(self) -> str:
        return "web"

    @property
    def description(self) -> str:
        return "Autonomous web browsing and task execution via Playwright"

    def get_tools(self) -> list[Tool]:
        return [
            Tool(
                name="run_web_agent",
                description="Opens a web browser and performs a task according to the prompt.",
                parameters=[ToolParameter("prompt", ToolParameterType.STRING, "Detailed instructions for the web agent.")],
                non_blocking=True,
            ),
        ]

    async def handle_tool_call(self, tool_name: str, args: dict[str, Any], **context) -> AgentResult:
        if tool_name != "run_web_agent":
            return AgentResult(success=False, message=f"Unknown tool: {tool_name}")

        prompt = args.get("prompt", "")
        result = await self.run_task(prompt)
        return AgentResult(success=True, data={"response": result}, is_async=True)

    # --- Browser automation (provider-agnostic) ---

    @staticmethod
    def _denormalize(val: int, max_val: int) -> int:
        return int((val / 1000) * max_val)

    async def _execute_actions(self, function_calls: list[dict]) -> list[dict]:
        """Execute browser actions from tool calls. Returns action results."""
        results = []
        for call in function_calls:
            fn_name = call.get("name", "")
            args = call.get("args", {})
            result_data = {}

            try:
                if fn_name == "navigate":
                    await self.page.goto(args["url"])
                elif fn_name == "go_back":
                    await self.page.go_back()
                elif fn_name == "go_forward":
                    await self.page.go_forward()
                elif fn_name == "search":
                    await self.page.goto("https://www.google.com")
                elif fn_name == "wait_5_seconds":
                    await asyncio.sleep(5)
                elif fn_name == "click_at":
                    x = self._denormalize(args["x"], SCREEN_WIDTH)
                    y = self._denormalize(args["y"], SCREEN_HEIGHT)
                    await self.page.mouse.click(x, y)
                elif fn_name == "type_text_at":
                    x = self._denormalize(args["x"], SCREEN_WIDTH)
                    y = self._denormalize(args["y"], SCREEN_HEIGHT)
                    await self.page.mouse.click(x, y)
                    if args.get("clear_before_typing", True):
                        await self.page.keyboard.press("Control+A")
                        await self.page.keyboard.press("Backspace")
                    await self.page.keyboard.type(args.get("text", ""))
                    if args.get("press_enter", False):
                        await self.page.keyboard.press("Enter")
                elif fn_name == "hover_at":
                    x = self._denormalize(args["x"], SCREEN_WIDTH)
                    y = self._denormalize(args["y"], SCREEN_HEIGHT)
                    await self.page.mouse.move(x, y)
                elif fn_name == "drag_and_drop":
                    sx = self._denormalize(args["x"], SCREEN_WIDTH)
                    sy = self._denormalize(args["y"], SCREEN_HEIGHT)
                    ex = self._denormalize(args["destination_x"], SCREEN_WIDTH)
                    ey = self._denormalize(args["destination_y"], SCREEN_HEIGHT)
                    await self.page.mouse.move(sx, sy)
                    await self.page.mouse.down()
                    await self.page.mouse.move(ex, ey)
                    await self.page.mouse.up()
                elif fn_name == "key_combination":
                    await self.page.keyboard.press(args.get("keys", ""))
                elif fn_name in ("scroll_document", "scroll_at"):
                    magnitude = args.get("magnitude", 800)
                    direction = args.get("direction", "down")
                    if fn_name == "scroll_at":
                        x = self._denormalize(args["x"], SCREEN_WIDTH)
                        y = self._denormalize(args["y"], SCREEN_HEIGHT)
                        await self.page.mouse.move(x, y)
                    dx, dy = 0, 0
                    if direction == "down": dy = magnitude
                    elif direction == "up": dy = -magnitude
                    elif direction == "right": dx = magnitude
                    elif direction == "left": dx = -magnitude
                    await self.page.mouse.wheel(dx, dy)

                await asyncio.sleep(1)  # Let UI settle
            except Exception as e:
                result_data = {"error": str(e)}

            results.append({"name": fn_name, "result": result_data})
        return results

    async def _take_screenshot(self) -> bytes:
        return await self.page.screenshot(type="png")

    async def run_task(self, prompt: str) -> str:
        """Run the web agent with the given prompt."""
        final_response = "Agent finished without a final summary."

        async with async_playwright() as p:
            self.browser = await p.chromium.launch(headless=True)
            self.context = await self.browser.new_context(
                viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self.page = await self.context.new_page()
            await self.page.goto("https://www.google.com")

            # Take initial screenshot
            screenshot = await self._take_screenshot()
            encoded = base64.b64encode(screenshot).decode("utf-8")
            self._bus.emit_nowait(Event(
                type=Events.WEB_UPDATE,
                data={"screenshot": encoded, "log": "Web Agent Initialized"},
                source=self.name,
            ))

            # Build conversation with initial screenshot
            messages = [
                Message(
                    role=MessageRole.USER,
                    content=prompt,
                    attachments=[{"type": "image", "data": screenshot, "mime_type": "image/png"}],
                ),
            ]

            for turn in range(MAX_TURNS):
                try:
                    response = await self._llm.generate(
                        messages=messages,
                        thinking=True,
                    )
                except Exception as e:
                    self._bus.emit_nowait(Event(
                        type=Events.WEB_UPDATE,
                        data={"screenshot": None, "log": f"Error: {e}"},
                        source=self.name,
                    ))
                    break

                # Record assistant response
                if response.text:
                    final_response = response.text
                    messages.append(Message(role=MessageRole.ASSISTANT, content=response.text))

                if not response.tool_calls:
                    self._bus.emit_nowait(Event(
                        type=Events.WEB_UPDATE,
                        data={"screenshot": None, "log": "Task Finished"},
                        source=self.name,
                    ))
                    break

                # Convert tool calls to action dicts
                actions = [{"name": tc.name, "args": tc.args} for tc in response.tool_calls]

                # Execute browser actions
                results = await self._execute_actions(actions)

                # Take new screenshot
                screenshot = await self._take_screenshot()
                encoded = base64.b64encode(screenshot).decode("utf-8")
                actions_log = ", ".join(r["name"] for r in results)
                self._bus.emit_nowait(Event(
                    type=Events.WEB_UPDATE,
                    data={"screenshot": encoded, "log": f"Executed: {actions_log}"},
                    source=self.name,
                ))

                # Send results + screenshot back as user message
                messages.append(Message(
                    role=MessageRole.USER,
                    content=f"Actions executed: {actions_log}. Current URL: {self.page.url}",
                    attachments=[{"type": "image", "data": screenshot, "mime_type": "image/png"}],
                ))

            await self.browser.close()

        self._bus.emit_nowait(Event(
            type=Events.WEB_RESULT,
            data={"response": final_response},
            source=self.name,
        ))
        return final_response
