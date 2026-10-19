from services.capability_profiles import model_id
import asyncio
import base64
import io
import os
import traceback
from dotenv import load_dotenv
import cv2
import pyaudio
import PIL.Image
import argparse
import math
import struct
import time

from google import genai
from google.genai import types
from services.live_config import make_live_config
from project_manager import ProjectManager

FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

MODEL = model_id("voice")
DEFAULT_MODE = "camera"

load_dotenv()


def is_invalid_api_key_error(error):
    message = str(error)
    lowered = message.lower()
    return (
        "API_KEY_INVALID" in message
        or "api key not valid" in lowered
        or "invalid api key" in lowered
    )


class AudioLoop:
    def __init__(
        self,
        video_mode=DEFAULT_MODE,
        on_audio_data=None,
        on_transcription=None,
        on_project_update=None,
        on_error=None,
        on_status=None,
        input_device_index=None,
        input_device_name=None,
        output_device_index=None,
        project_manager=None,
        tool_bridge=None,
    ):
        self.tool_bridge = tool_bridge
        self.config = make_live_config(tool_bridge)
        self.client = genai.Client(
            http_options={"api_version": "v1beta"}, api_key=os.getenv("GEMINI_API_KEY")
        )
        try:
            self.pya = pyaudio.PyAudio()
        except Exception:
            self.client.close()
            raise
        self.output_stream = None
        self.video_mode = video_mode
        self.on_audio_data = on_audio_data
        self.on_transcription = on_transcription
        self.on_project_update = on_project_update
        self.on_error = on_error
        self.on_status = on_status
        self.input_device_index = input_device_index
        self.input_device_name = input_device_name
        self.output_device_index = output_device_index

        self.chat_buffer = {"sender": None, "text": ""}  # For aggregating chunks

        # Track last transcription text to calculate deltas (Gemini sends cumulative text)
        self._last_input_transcription = ""
        self._last_output_transcription = ""

        self.audio_in_queue = None
        self.out_queue = None
        self.paused = False

        self.session = None

        self.stop_event = asyncio.Event()

        # Video buffering state
        self._latest_image_payload = None
        # VAD State
        self._is_speaking = False
        self._silence_start_time = None

        if project_manager:
            self.project_manager = project_manager
        else:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            self.project_manager = ProjectManager(project_root)

    def flush_chat(self):
        """Forces the current chat buffer to be written to log."""
        if self.chat_buffer["sender"] and self.chat_buffer["text"].strip():
            self.project_manager.log_chat(self.chat_buffer["sender"], self.chat_buffer["text"])
            self.chat_buffer = {"sender": None, "text": ""}
        # Reset transcription tracking for new turn
        self._last_input_transcription = ""
        self._last_output_transcription = ""

    def set_paused(self, paused):
        self.paused = paused

    def stop(self):
        self.stop_event.set()

    def close(self):
        errors = []
        for name in ("audio_stream", "output_stream", "pya", "client"):
            value = getattr(self, name, None)
            setattr(self, name, None)
            if value is not None:
                try:
                    value.terminate() if name == "pya" else value.close()
                except Exception as exc:
                    errors.append(exc)
        if errors:
            raise errors[0]

    def clear_audio_queue(self):
        """Clears the queue of pending audio chunks to stop playback immediately."""
        try:
            count = 0
            while not self.audio_in_queue.empty():
                self.audio_in_queue.get_nowait()
                count += 1
            if count > 0:
                print(
                    f"[INARA DEBUG] [AUDIO] Cleared {count} chunks from playback queue due to interruption."
                )
        except Exception as e:
            print(f"[INARA DEBUG] [ERR] Failed to clear audio queue: {e}")

    async def send_frame(self, frame_data):
        # Update the latest frame payload
        if isinstance(frame_data, bytes):
            b64_data = base64.b64encode(frame_data).decode("utf-8")
        else:
            b64_data = frame_data

        # Store as the designated "next frame to send"
        self._latest_image_payload = {"mime_type": "image/jpeg", "data": b64_data}
        # No event signal needed - listen_audio pulls it

    async def send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send(input=msg, end_of_turn=False)

    async def listen_audio(self):
        mic_info = self.pya.get_default_input_device_info()

        # Resolve Input Device by Name if provided
        resolved_input_device_index = None

        if self.input_device_name:
            print(f"[INARA] Attempting to find input device matching: '{self.input_device_name}'")
            count = self.pya.get_device_count()
            best_match = None

            for i in range(count):
                try:
                    info = self.pya.get_device_info_by_index(i)
                    if info["maxInputChannels"] > 0:
                        name = info.get("name", "")
                        # Simple case-insensitive check
                        if (
                            self.input_device_name.lower() in name.lower()
                            or name.lower() in self.input_device_name.lower()
                        ):
                            print(f"   Candidate {i}: {name}")
                            # Prioritize exact match or very close match if possible, but first match is okay for now
                            resolved_input_device_index = i
                            best_match = name
                            break
                except Exception:
                    continue

            if resolved_input_device_index is not None:
                print(
                    f"[INARA] Resolved input device '{self.input_device_name}' to index {resolved_input_device_index} ({best_match})"
                )
            else:
                print(
                    f"[INARA] Could not find device matching '{self.input_device_name}'. Checking index..."
                )

        # Fallback to index if Name lookup failed or wasn't provided
        if resolved_input_device_index is None and self.input_device_index is not None:
            try:
                resolved_input_device_index = int(self.input_device_index)
                print(f"[INARA] Requesting Input Device Index: {resolved_input_device_index}")
            except ValueError:
                print(
                    f"[INARA] Invalid device index '{self.input_device_index}', reverting to default."
                )
                resolved_input_device_index = None

        if resolved_input_device_index is None:
            print("[INARA] Using Default Input Device")

        try:
            self.audio_stream = await asyncio.to_thread(
                self.pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                input_device_index=resolved_input_device_index
                if resolved_input_device_index is not None
                else mic_info["index"],
                frames_per_buffer=CHUNK_SIZE,
            )
        except OSError as e:
            print(f"[INARA] [ERR] Failed to open audio input stream: {e}")
            print(
                "[INARA] [WARN] Audio features will be disabled. Please check microphone permissions."
            )
            return

        if __debug__:
            kwargs = {"exception_on_overflow": False}
        else:
            kwargs = {}

        # VAD Constants
        VAD_THRESHOLD = 800  # Adj based on mic sensitivity (800 is conservative for 16-bit)
        SILENCE_DURATION = 0.5  # Seconds of silence to consider "done speaking"

        while True:
            if self.paused:
                await asyncio.sleep(0.1)
                continue

            try:
                data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, **kwargs)

                # 1. Send Audio
                if self.out_queue:
                    await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})

                # 2. VAD Logic for Video
                # rms = audioop.rms(data, 2)
                # Replacement for audioop.rms(data, 2)
                count = len(data) // 2
                if count > 0:
                    shorts = struct.unpack(f"<{count}h", data)
                    sum_squares = sum(s**2 for s in shorts)
                    rms = int(math.sqrt(sum_squares / count))
                else:
                    rms = 0

                if rms > VAD_THRESHOLD:
                    # Speech Detected
                    self._silence_start_time = None

                    if not self._is_speaking:
                        # NEW Speech Utterance Started
                        self._is_speaking = True
                        print(
                            f"[INARA DEBUG] [VAD] Speech Detected (RMS: {rms}). Sending Video Frame."
                        )

                        # Send ONE frame
                        if self._latest_image_payload and self.out_queue:
                            await self.out_queue.put(self._latest_image_payload)
                        else:
                            print("[INARA DEBUG] [VAD] No video frame available to send.")

                else:
                    # Silence
                    if self._is_speaking:
                        if self._silence_start_time is None:
                            self._silence_start_time = time.time()

                        elif time.time() - self._silence_start_time > SILENCE_DURATION:
                            # Silence confirmed, reset state
                            print("[INARA DEBUG] [VAD] Silence detected. Resetting speech state.")
                            self._is_speaking = False
                            self._silence_start_time = None

            except Exception as e:
                print(f"Error reading audio: {e}")
                await asyncio.sleep(0.1)

    async def receive_audio(self):
        "Background task to reads from the websocket and write pcm chunks to the output queue"
        try:
            while True:
                turn = self.session.receive()
                async for response in turn:
                    # 1. Handle Audio Data
                    if data := response.data:
                        self.audio_in_queue.put_nowait(data)
                        # NOTE: 'continue' removed here to allow processing transcription/tools in same packet

                    # 2. Handle Transcription (User & Model)
                    if response.server_content:
                        if response.server_content.input_transcription:
                            transcript = response.server_content.input_transcription.text
                            if transcript:
                                # Skip if this is an exact duplicate event
                                if transcript != self._last_input_transcription:
                                    # Calculate delta (Gemini may send cumulative or chunk-based text)
                                    delta = transcript
                                    if transcript.startswith(self._last_input_transcription):
                                        delta = transcript[len(self._last_input_transcription) :]
                                    self._last_input_transcription = transcript

                                    # Only send if there's new text
                                    if delta:
                                        # User is speaking, so interrupt model playback!
                                        self.clear_audio_queue()

                                        # Send to frontend (Streaming)
                                        if self.on_transcription:
                                            self.on_transcription({"sender": "User", "text": delta})

                                        # Buffer for Logging
                                        if self.chat_buffer["sender"] != "User":
                                            # Flush previous if exists
                                            if (
                                                self.chat_buffer["sender"]
                                                and self.chat_buffer["text"].strip()
                                            ):
                                                self.project_manager.log_chat(
                                                    self.chat_buffer["sender"],
                                                    self.chat_buffer["text"],
                                                )
                                            # Start new
                                            self.chat_buffer = {"sender": "User", "text": delta}
                                        else:
                                            # Append
                                            self.chat_buffer["text"] += delta

                        if response.server_content.output_transcription:
                            transcript = response.server_content.output_transcription.text
                            if transcript:
                                # Skip if this is an exact duplicate event
                                if transcript != self._last_output_transcription:
                                    # Calculate delta (Gemini may send cumulative or chunk-based text)
                                    delta = transcript
                                    if transcript.startswith(self._last_output_transcription):
                                        delta = transcript[len(self._last_output_transcription) :]
                                    self._last_output_transcription = transcript

                                    # Only send if there's new text
                                    if delta:
                                        # Send to frontend (Streaming)
                                        if self.on_transcription:
                                            self.on_transcription(
                                                {"sender": "INARA", "text": delta}
                                            )

                                        # Buffer for Logging
                                        if self.chat_buffer["sender"] != "INARA":
                                            # Flush previous
                                            if (
                                                self.chat_buffer["sender"]
                                                and self.chat_buffer["text"].strip()
                                            ):
                                                self.project_manager.log_chat(
                                                    self.chat_buffer["sender"],
                                                    self.chat_buffer["text"],
                                                )
                                            # Start new
                                            self.chat_buffer = {"sender": "INARA", "text": delta}
                                        else:
                                            # Append
                                            self.chat_buffer["text"] += delta

                        # Flush buffer on turn completion if needed,
                        # but usually better to wait for sender switch or explicit end.
                        # We can also check turn_complete signal if available in response.server_content.model_turn etc

                    # All advertised functions use the injected shared dispatcher.
                    if response.tool_call:
                        function_responses = []
                        for fc in response.tool_call.function_calls:
                            result = (
                                await self.tool_bridge.call(fc.name, dict(fc.args or {}))
                                if self.tool_bridge
                                else {
                                    "error": "tool_unavailable",
                                    "message": "Voice tools require the supported application.",
                                }
                            )
                            function_responses.append(
                                types.FunctionResponse(
                                    id=fc.id, name=fc.name, response={"result": result}
                                )
                            )
                        if function_responses:
                            await self.session.send_tool_response(
                                function_responses=function_responses
                            )

                # Turn/Response Loop Finished
                self.flush_chat()

                while not self.audio_in_queue.empty():
                    self.audio_in_queue.get_nowait()
        except Exception as e:
            print(f"Error in receive_audio: {e}")
            traceback.print_exc()
            # CRITICAL: Re-raise to crash the TaskGroup and trigger outer loop reconnect
            raise e

    async def play_audio(self):
        stream = await asyncio.to_thread(
            self.pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
            output_device_index=self.output_device_index,
        )
        self.output_stream = stream
        while True:
            bytestream = await self.audio_in_queue.get()
            if self.on_audio_data:
                self.on_audio_data(bytestream)
            await asyncio.to_thread(stream.write, bytestream)

    async def get_frames(self):
        cap = await asyncio.to_thread(cv2.VideoCapture, 0, cv2.CAP_AVFOUNDATION)
        while True:
            if self.paused:
                await asyncio.sleep(0.1)
                continue
            frame = await asyncio.to_thread(self._get_frame, cap)
            if frame is None:
                break
            await asyncio.sleep(1.0)
            if self.out_queue:
                await self.out_queue.put(frame)
        cap.release()

    def _get_frame(self, cap):
        ret, frame = cap.read()
        if not ret:
            return None
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(frame_rgb)
        img.thumbnail([1024, 1024])
        image_io = io.BytesIO()
        img.save(image_io, format="jpeg")
        image_io.seek(0)
        image_bytes = image_io.read()
        return {"mime_type": "image/jpeg", "data": base64.b64encode(image_bytes).decode()}

    async def _get_screen(self):
        pass

    async def get_screen(self):
        pass

    async def run(self, start_message=None):
        retry_delay = 1
        is_reconnect = False

        while not self.stop_event.is_set():
            try:
                print("[INARA DEBUG] [CONNECT] Connecting to Gemini Live API...")
                async with (
                    self.client.aio.live.connect(model=MODEL, config=self.config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session = session

                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=10)

                    if self.on_status:
                        self.on_status("INARA Started")

                    tg.create_task(self.send_realtime())
                    tg.create_task(self.listen_audio())
                    # tg.create_task(self._process_video_queue()) # Removed in favor of VAD

                    if self.video_mode == "camera":
                        tg.create_task(self.get_frames())
                    elif self.video_mode == "screen":
                        tg.create_task(self.get_screen())

                    tg.create_task(self.receive_audio())
                    tg.create_task(self.play_audio())

                    # Handle Startup vs Reconnect Logic
                    if not is_reconnect:
                        if start_message:
                            print(f"[INARA DEBUG] [INFO] Sending start message: {start_message}")
                            await self.session.send(input=start_message, end_of_turn=True)

                        # Sync Project State
                        if self.on_project_update and self.project_manager:
                            self.on_project_update(self.project_manager.current_project)

                    else:
                        print("[INARA DEBUG] [RECONNECT] Connection restored.")
                        # Restore Context
                        print(
                            "[INARA DEBUG] [RECONNECT] Fetching recent chat history to restore context..."
                        )
                        history = self.project_manager.get_recent_chat_history(limit=10)

                        context_msg = "System Notification: Connection was lost and just re-established. Here is the recent chat history to help you resume seamlessly:\n\n"
                        for entry in history:
                            sender = entry.get("sender", "Unknown")
                            text = entry.get("text", "")
                            context_msg += f"[{sender}]: {text}\n"

                        context_msg += "\nPlease acknowledge the reconnection to the user (e.g. 'I lost connection for a moment, but I'm back...') and resume what you were doing."

                        print("[INARA DEBUG] [RECONNECT] Sending restoration context to model...")
                        await self.session.send(input=context_msg, end_of_turn=True)

                    # Reset retry delay on successful connection
                    retry_delay = 1

                    # Wait until stop event, or until the session task group exits (which happens on error)
                    # Actually, the TaskGroup context manager will exit if any tasks fail/cancel.
                    # We need to keep this block alive.
                    # The original code just waited on stop_event, but that doesn't account for session death.
                    # We should rely on the TaskGroup raising an exception when subtasks fail (like receive_audio).

                    # However, since receive_audio is a task in the group, if it crashes (connection closed),
                    # the group will cancel others and exit. We catch that exit below.

                    # We can await stop_event, but if the connection dies, receive_audio crashes -> group closes -> we exit `async with` -> restart loop.
                    # To ensure we don't block indefinitely if connection dies silently (unlikely with receive_audio), we just wait.
                    await self.stop_event.wait()

            except asyncio.CancelledError:
                print("[INARA DEBUG] [STOP] Main loop cancelled.")
                break

            except Exception as e:
                # This catches the ExceptionGroup from TaskGroup or direct exceptions
                print(f"[INARA DEBUG] [ERR] Connection Error: {e}")

                if is_invalid_api_key_error(e):
                    if self.on_status:
                        self.on_status("AI Unavailable")
                    if self.on_error:
                        self.on_error(
                            "AI unavailable: API key not valid. Please update GEMINI_API_KEY."
                        )
                    break

                if self.stop_event.is_set():
                    break

                print(f"[INARA DEBUG] [RETRY] Reconnecting in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 10)  # Exponential backoff capped at 10s
                is_reconnect = True  # Next loop will be a reconnect

            finally:
                # Cleanup before retry
                if hasattr(self, "audio_stream") and self.audio_stream:
                    try:
                        self.audio_stream.close()
                        self.audio_stream = None
                    except Exception:
                        pass


def get_input_devices():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get("deviceCount")
    devices = []
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get("maxInputChannels")) > 0:
            devices.append((i, p.get_device_info_by_host_api_device_index(0, i).get("name")))
    p.terminate()
    return devices


def get_output_devices():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get("deviceCount")
    devices = []
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get("maxOutputChannels")) > 0:
            devices.append((i, p.get_device_info_by_host_api_device_index(0, i).get("name")))
    p.terminate()
    return devices


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        type=str,
        default=DEFAULT_MODE,
        help="pixels to stream from",
        choices=["camera", "screen", "none"],
    )
    args = parser.parse_args()
    main = AudioLoop(video_mode=args.mode)
    asyncio.run(main.run())
