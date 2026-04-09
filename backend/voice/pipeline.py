"""
Voice Pipeline  - Orchestrates the full voice conversation loop.

Connects the audio I/O layer, VAD, transcription processing, and the
Gemini Live API into a single coherent pipeline:

    Mic → AudioInput → VAD → Gemini Live API → AudioOutput → Speaker
                         ↕                        ↕
                    VideoCapture           TranscriptionManager
                         ↕                        ↕
                    Tool Dispatch              Chat Log

This replaces the monolithic AudioLoop from inara.py with a composed
pipeline of clean, testable components.
"""

import asyncio
import os
import sys
import uuid
import traceback
from typing import Optional, Callable, Any

from dotenv import load_dotenv

# Ensure backend/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google import genai
from google.genai import types

from core.event_bus import EventBus, Event, Events
from voice.audio_io import AudioInput, AudioOutput, VideoCapture, clear_queue
from voice.wake_word import VoiceActivityDetector
from voice.stt import TranscriptionManager
from voice.tts import SpeechOutputManager, INARA_SYSTEM_INSTRUCTION, INARA_VOICE_NAME


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
DEFAULT_VIDEO_MODE = "camera"
MAX_RETRY_DELAY = 10  # seconds


# ---------------------------------------------------------------------------
# Voice Pipeline
# ---------------------------------------------------------------------------

class VoicePipeline:
    """
    INARA's voice conversation pipeline.

    Manages the full lifecycle of a voice session:
    1. Opens microphone and speaker streams
    2. Connects to Gemini Live API
    3. Sends audio + video frames to Gemini
    4. Receives audio responses and transcription
    5. Handles tool calls (dispatched via EventBus)
    6. Reconnects automatically on connection loss

    All frontend communication goes through the EventBus  - no callbacks.
    Tool calls are dispatched to agents via the bus, not handled inline.
    """

    def __init__(
        self,
        event_bus: EventBus,
        video_mode: str = DEFAULT_VIDEO_MODE,
        input_device_name: Optional[str] = None,
        input_device_index: Optional[int] = None,
        output_device_index: Optional[int] = None,
        tools: Optional[list] = None,
        system_instruction: Optional[str] = None,
    ):
        self._bus = event_bus
        self._video_mode = video_mode

        # Audio I/O
        self._audio_in = AudioInput(
            device_name=input_device_name,
            device_index=input_device_index,
        )
        self._speech_out = SpeechOutputManager(
            output_device_index=output_device_index,
            on_audio_data=self._on_audio_data,
        )

        # VAD
        self._vad = VoiceActivityDetector()
        self._vad.on_speech_start = self._on_speech_start

        # Video
        self._video = VideoCapture() if video_mode == "camera" else None
        self._latest_frame: Optional[dict] = None

        # Transcription
        self._transcription = TranscriptionManager(
            on_transcription=self._emit_transcription,
            on_log=self._log_chat,
            on_user_speech=self._on_user_speech,
        )

        # Gemini session state
        self._session = None
        self._out_queue: Optional[asyncio.Queue] = None
        self._stop_event = asyncio.Event()

        # Tool confirmation
        self._permissions: dict[str, bool] = {}
        self._pending_confirmations: dict[str, asyncio.Future] = {}

        # Project manager
        self._project_manager = None

        # Gemini config
        self._tools = tools or []
        self._system_instruction = system_instruction or INARA_SYSTEM_INSTRUCTION

        # Gemini client (lazy init)
        self._client = None

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def run(self, start_message: Optional[str] = None):
        """
        Main entry point. Connects to Gemini and runs the voice loop.
        Automatically reconnects on failure with exponential backoff.
        """
        self._init_client()
        self._init_project_manager()

        config = self._build_config()
        retry_delay = 1
        is_reconnect = False

        while not self._stop_event.is_set():
            try:
                print("[INARA] [VOICE] Connecting to Gemini Live API...")
                async with (
                    self._client.aio.live.connect(model=MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self._session = session
                    self._out_queue = asyncio.Queue(maxsize=10)

                    # Launch concurrent tasks
                    tg.create_task(self._send_loop())
                    tg.create_task(self._listen_loop())
                    tg.create_task(self._receive_loop())
                    tg.create_task(self._speech_out.play_loop())

                    if self._video and self._video_mode == "camera":
                        tg.create_task(self._video.capture_loop(
                            self._out_queue,
                            interval=1.0,
                            paused_fn=lambda: self._stop_event.is_set(),
                        ))

                    # Startup vs reconnect
                    if not is_reconnect:
                        await self._handle_startup(start_message)
                    else:
                        await self._handle_reconnect()

                    retry_delay = 1
                    await self._stop_event.wait()

            except asyncio.CancelledError:
                print("[INARA] [VOICE] Pipeline cancelled.")
                break
            except Exception as e:
                print(f"[INARA] [VOICE] Connection error: {e}")
                traceback.print_exc()
                if self._stop_event.is_set():
                    break
                print(f"[INARA] [VOICE] Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)
                is_reconnect = True
            finally:
                self._audio_in.close()

    def stop(self):
        """Signal the pipeline to stop."""
        self._stop_event.set()
        self._speech_out.stop()

    def set_paused(self, paused: bool):
        """Pause/resume audio capture (speaker output continues)."""
        self._paused = paused

    def update_permissions(self, permissions: dict[str, bool]):
        """Update tool permission settings."""
        self._permissions.update(permissions)
        print(f"[INARA] [VOICE] Permissions updated: {permissions}")

    def resolve_tool_confirmation(self, request_id: str, confirmed: bool):
        """Resolve a pending tool confirmation from the frontend."""
        if request_id in self._pending_confirmations:
            future = self._pending_confirmations[request_id]
            if not future.done():
                future.set_result(confirmed)
            else:
                print(f"[INARA] [VOICE] [WARN] Confirmation {request_id} already resolved.")
        else:
            print(f"[INARA] [VOICE] [WARN] Confirmation {request_id} not found.")

    async def send_frame(self, frame_data):
        """Buffer a video frame for VAD-triggered sending."""
        import base64
        if isinstance(frame_data, bytes):
            b64 = base64.b64encode(frame_data).decode("utf-8")
        else:
            b64 = frame_data
        self._latest_frame = {"mime_type": "image/jpeg", "data": b64}

    # -----------------------------------------------------------------------
    # Internal: Gemini Setup
    # -----------------------------------------------------------------------

    def _init_client(self):
        """Initialize the Gemini client."""
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not found in environment. Check your .env file.")
        self._client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=api_key,
        )

    def _init_project_manager(self):
        """Initialize the project manager."""
        from project_manager import ProjectManager
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        self._project_manager = ProjectManager(project_root)

    def _build_config(self) -> types.LiveConnectConfig:
        """Build the Gemini Live API config."""
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=self._system_instruction,
            tools=self._tools,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=INARA_VOICE_NAME,
                    )
                )
            ),
        )

    # -----------------------------------------------------------------------
    # Internal: Core Loops
    # -----------------------------------------------------------------------

    async def _send_loop(self):
        """Sends queued audio/video/text to the Gemini session."""
        while True:
            msg = await self._out_queue.get()
            if self._session:
                await self._session.send(input=msg, end_of_turn=False)

    async def _listen_loop(self):
        """Captures microphone audio, runs VAD, and queues for Gemini."""
        opened = await self._audio_in.open()
        if not opened:
            return

        while not self._stop_event.is_set():
            chunk = await self._audio_in.read_chunk()
            if chunk is None:
                await asyncio.sleep(0.1)
                continue

            # Send audio to Gemini
            if self._out_queue:
                await self._out_queue.put({"data": chunk, "mime_type": "audio/pcm"})

            # Run VAD  - may trigger video frame send on speech start
            self._vad.process(chunk)

    async def _receive_loop(self):
        """Receives responses from Gemini  - audio, transcription, tool calls."""
        try:
            while True:
                turn = self._session.receive()
                async for response in turn:
                    # 1. Audio data → playback queue
                    if data := response.data:
                        self._speech_out.enqueue(data)

                    # 2. Transcription
                    if response.server_content:
                        self._handle_transcription(response.server_content)

                    # 3. Tool calls
                    if response.tool_call:
                        await self._handle_tool_calls(response.tool_call)

        except Exception as e:
            print(f"[INARA] [VOICE] Receive error: {e}")
            traceback.print_exc()
            raise

    # -----------------------------------------------------------------------
    # Internal: Transcription
    # -----------------------------------------------------------------------

    def _handle_transcription(self, server_content):
        """Process input and output transcription from Gemini."""
        if server_content.input_transcription:
            text = server_content.input_transcription.text
            if text:
                self._transcription.process_input(text)

        if server_content.output_transcription:
            text = server_content.output_transcription.text
            if text:
                self._transcription.process_output(text)

    # -----------------------------------------------------------------------
    # Internal: Tool Handling
    # -----------------------------------------------------------------------

    async def _handle_tool_calls(self, tool_call):
        """Process tool calls from Gemini and dispatch to agents."""
        function_responses = []

        for fc in tool_call.function_calls:
            # Permission check
            allowed = await self._check_permission(fc)
            if not allowed:
                function_responses.append(types.FunctionResponse(
                    id=fc.id,
                    name=fc.name,
                    response={"result": "User denied the request to use this tool."},
                ))
                continue

            # Dispatch tool call
            result = await self._dispatch_tool(fc)
            if result is not None:
                function_responses.append(types.FunctionResponse(
                    id=fc.id,
                    name=fc.name,
                    response={"result": result},
                ))

        # Send function responses back to Gemini
        if function_responses and self._session:
            try:
                await self._session.send(input=function_responses, end_of_turn=False)
            except Exception as e:
                print(f"[INARA] [VOICE] Error sending tool responses: {e}")

    async def _check_permission(self, fc) -> bool:
        """Check if a tool call is allowed. May block waiting for user confirmation."""
        requires_confirmation = self._permissions.get(fc.name, True)

        if not requires_confirmation:
            print(f"[INARA] [VOICE] [TOOL] '{fc.name}' auto-allowed.")
            return True

        # Request confirmation from frontend
        request_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._pending_confirmations[request_id] = future

        print(f"[INARA] [VOICE] [TOOL] Requesting confirmation for '{fc.name}' (ID: {request_id})")
        self._bus.emit_nowait(Event(
            type=Events.TOOL_CALL_REQUESTED,
            data={"id": request_id, "tool": fc.name, "args": fc.args},
            source="voice",
        ))

        try:
            confirmed = await future
        finally:
            self._pending_confirmations.pop(request_id, None)

        if not confirmed:
            print(f"[INARA] [VOICE] [TOOL] '{fc.name}' denied by user.")
        return confirmed

    async def _dispatch_tool(self, fc) -> Optional[str]:
        """
        Dispatch a tool call to the appropriate handler via EventBus.

        Returns a result string to send back to Gemini, or None if the
        tool runs asynchronously (e.g., CAD generation fires and forgets).
        """
        name = fc.name
        args = fc.args or {}
        print(f"[INARA] [VOICE] [TOOL] Dispatching: '{name}'")

        # Emit tool call event  - agents subscribed on the bus will handle it
        self._bus.emit_nowait(Event(
            type=Events.TOOL_CALL_REQUESTED,
            data={"tool": name, "args": args, "source": "voice"},
            source="voice",
        ))

        # Tools that run async (fire and forget  - result comes back via events)
        async_tools = {"generate_cad", "iterate_cad", "run_web_agent"}
        if name in async_tools:
            return f"{name} started. Do not reply to this message."

        # Tools that need a synchronous result for the model
        # These are dispatched to the project manager or other sync handlers
        if name == "create_project":
            return self._handle_create_project(args)
        elif name == "switch_project":
            return self._handle_switch_project(args)
        elif name == "list_projects":
            return self._handle_list_projects()
        elif name == "write_file":
            return await self._handle_write_file(args)
        elif name == "read_directory":
            return self._handle_read_directory(args)
        elif name == "read_file":
            return self._handle_read_file(args)
        elif name in ("list_smart_devices", "control_light", "discover_printers",
                       "print_stl", "get_print_status"):
            # These are handled by agents via the event bus
            return f"{name} dispatched."

        return f"Unknown tool: {name}"

    # -----------------------------------------------------------------------
    # Internal: Project/File Tool Handlers
    # -----------------------------------------------------------------------

    def _handle_create_project(self, args: dict) -> str:
        name = args.get("name", "untitled")
        self._project_manager.create_project(name)
        self._bus.emit_nowait(Event(
            type=Events.PROJECT_CHANGED,
            data={"project": name},
            source="voice",
        ))
        return f"Project '{name}' created and set as active."

    def _handle_switch_project(self, args: dict) -> str:
        name = args.get("name", "")
        self._project_manager.switch_project(name)
        context = self._project_manager.get_project_context()
        self._bus.emit_nowait(Event(
            type=Events.PROJECT_CHANGED,
            data={"project": name},
            source="voice",
        ))
        return f"Switched to project '{name}'. Context: {context}"

    def _handle_list_projects(self) -> str:
        projects = self._project_manager.list_projects()
        current = self._project_manager.current_project
        lines = [f"  {'→ ' if p == current else '  '}{p}" for p in projects]
        return f"Projects:\n" + "\n".join(lines)

    async def _handle_write_file(self, args: dict) -> str:
        path = args.get("path", "")
        content = args.get("content", "")
        project_path = str(self._project_manager.get_current_project_path())
        final_path = os.path.join(project_path, path) if not os.path.isabs(path) else path

        try:
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            with open(final_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"File written: {final_path}"
        except Exception as e:
            return f"Write failed: {e}"

    def _handle_read_directory(self, args: dict) -> str:
        path = args.get("path", ".")
        project_path = str(self._project_manager.get_current_project_path())
        final_path = os.path.join(project_path, path) if not os.path.isabs(path) else path

        try:
            entries = os.listdir(final_path)
            return f"Contents of {final_path}:\n" + "\n".join(f"  {e}" for e in entries)
        except Exception as e:
            return f"Read directory failed: {e}"

    def _handle_read_file(self, args: dict) -> str:
        path = args.get("path", "")
        project_path = str(self._project_manager.get_current_project_path())
        final_path = os.path.join(project_path, path) if not os.path.isabs(path) else path

        try:
            with open(final_path, "r", encoding="utf-8") as f:
                content = f.read()
            return f"Contents of {final_path}:\n{content}"
        except Exception as e:
            return f"Read file failed: {e}"

    # -----------------------------------------------------------------------
    # Internal: Callbacks & Events
    # -----------------------------------------------------------------------

    def _on_audio_data(self, data: bytes):
        """Called when audio data is about to be played  - forward to frontend."""
        self._bus.emit_nowait(Event(
            type=Events.VOICE_AUDIO_OUT,
            data={"audio": data},
            source="voice",
        ))

    def _on_speech_start(self):
        """Called when VAD detects user started speaking  - send buffered video frame."""
        if self._latest_frame and self._out_queue:
            try:
                self._out_queue.put_nowait(self._latest_frame)
            except asyncio.QueueFull:
                pass

    def _on_user_speech(self):
        """Called when user transcription is detected  - interrupt INARA's output."""
        self._speech_out.interrupt()

    def _emit_transcription(self, data: dict):
        """Forward transcription to frontend via event bus."""
        self._bus.emit_nowait(Event(
            type=Events.VOICE_TRANSCRIPTION,
            data=data,
            source="voice",
        ))

    def _log_chat(self, sender: str, text: str):
        """Log a chat message to the project manager."""
        if self._project_manager:
            self._project_manager.log_chat(sender, text)

    # -----------------------------------------------------------------------
    # Internal: Startup & Reconnect
    # -----------------------------------------------------------------------

    async def _handle_startup(self, start_message: Optional[str]):
        """Handle first connection  - send greeting and sync project state."""
        if start_message and self._session:
            print(f"[INARA] [VOICE] Sending start message...")
            await self._session.send(input=start_message, end_of_turn=True)

        if self._project_manager:
            self._bus.emit_nowait(Event(
                type=Events.PROJECT_CHANGED,
                data={"project": self._project_manager.current_project},
                source="voice",
            ))

    async def _handle_reconnect(self):
        """Handle reconnection  - restore context from chat history."""
        print("[INARA] [VOICE] Connection restored. Restoring context...")

        if not self._project_manager or not self._session:
            return

        history = self._project_manager.get_recent_chat_history(limit=10)
        context = (
            "System Notification: Connection was lost and re-established. "
            "Recent chat history:\n\n"
        )
        for entry in history:
            sender = entry.get("sender", "Unknown")
            text = entry.get("text", "")
            context += f"[{sender}]: {text}\n"

        context += (
            "\nPlease acknowledge the reconnection briefly "
            "and resume what you were doing."
        )

        await self._session.send(input=context, end_of_turn=True)
