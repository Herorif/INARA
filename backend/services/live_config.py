"""Gemini Live session configuration for JARVIS's spoken voice.

Importing this module opens no device or provider and imports no SDK; ``make_live_config``
imports google-genai only when a session is about to connect.

Field names follow the Live API docs (checked 26 Oct 2026):
- https://ai.google.dev/gemini-api/docs/live-guide (speech_config voice, input/output audio
  transcription, realtime_input_config automatic_activity_detection, interruptions)
- https://ai.google.dev/gemini-api/docs/live-session (context_window_compression sliding_window,
  session_resumption handle, go_away)
- https://ai.google.dev/gemini-api/docs/live-tools (function_declarations; asynchronous
  NON_BLOCKING calls are documented only for Gemini 2.5 Flash Live, so ask_brain is a normal
  blocking call and JARVIS acknowledges the request aloud before calling it)
"""

INPUT_RATE = 16000  # raw PCM16 mono little-endian into Live
OUTPUT_RATE = 24000  # raw PCM16 mono little-endian out of Live
VOICE_MODES = ("push_to_talk", "conversation")
VOICE_DEFAULTS = {"name": "Kore", "mode": "push_to_talk"}

# Prebuilt voices (https://ai.google.dev/gemini-api/docs/speech-generation, "Voice options";
# the Live guide says native audio models accept any voice of the TTS models).
PREBUILT_VOICES = (
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
)

VOICE_LINE = (
    "When speaking, keep answers short — one to three sentences — unless asked for detail; "
    "never read out long lists, code or URLs; offer to show details on screen instead."
)

ASK_BRAIN = {
    "name": "ask_brain",
    "description": (
        "Use for anything that needs tools, the owner's files/projects/reminders/devices, "
        "multi-step work or careful reasoning. Pass the owner's request in full with any "
        "context from this conversation. Before calling, tell the owner briefly that you are "
        "on it (for example 'One moment'). Returns the final answer to speak, condensed if "
        "long; actions may wait for the owner's approval on screen."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "request": {
                "type": "STRING",
                "description": "The owner's request, self-contained, in their language.",
            }
        },
        "required": ["request"],
    },
}
END_CONVERSATION = {
    "name": "end_conversation",
    "description": (
        "End the hands-free voice conversation when the owner says goodbye or asks you to "
        "stop listening. Say a short goodbye first."
    ),
}


def voice_settings(settings):
    """Validated ``voice.*`` values with defaults; unknown or stale values fall back."""
    voice = (settings or {}).get("voice")
    voice = voice if isinstance(voice, dict) else {}
    name = voice.get("name")
    mode = voice.get("mode")
    return {
        "name": name if name in PREBUILT_VOICES else VOICE_DEFAULTS["name"],
        "mode": mode if mode in VOICE_MODES else VOICE_DEFAULTS["mode"],
    }


def voice_instruction(settings):
    """The brain's stable persona plus the one spoken-style line."""
    from services.conversation import persona

    return persona(settings, VOICE_LINE)


def declarations(mode):
    return [ASK_BRAIN, *([END_CONVERSATION] if mode == "conversation" else [])]


def live_connect_config(*, system_instruction, voice_name, function_declarations,
                        automatic_activity_detection, handle=None, max_output_tokens=None):
    """The Live session shape shared by desktop voice and phone calls (telephony/agent.py):
    audio out in a prebuilt voice, captions both ways, barge-in, context-window
    compression and session resumption (``handle`` resumes a dropped session)."""
    from google.genai import types

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system_instruction,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        # Empty configs enable captions with automatic language detection (English or Malay).
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            # Without automatic detection the client sends activity start/end itself
            # (push-to-talk). With it the server detects speech, and new speech
            # interrupts the answer (barge-in).
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=not automatic_activity_detection
            ),
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()
        ),
        session_resumption=types.SessionResumptionConfig(handle=handle),
        tools=[types.Tool(function_declarations=list(function_declarations))],
        **({"max_output_tokens": max_output_tokens} if max_output_tokens else {}),
    )


def make_live_config(settings=None, *, mode="push_to_talk", handle=None, max_output_tokens=None):
    """LiveConnectConfig for one desktop voice connection; ``handle`` resumes a dropped session."""
    if mode not in VOICE_MODES:
        raise ValueError("Unknown voice mode")
    return live_connect_config(
        system_instruction=voice_instruction(settings),
        voice_name=voice_settings(settings)["name"],
        function_declarations=declarations(mode),
        # Push-to-talk: the renderer marks the hold. Conversation: server VAD.
        automatic_activity_detection=mode == "conversation",
        handle=handle,
        max_output_tokens=max_output_tokens,
    )
