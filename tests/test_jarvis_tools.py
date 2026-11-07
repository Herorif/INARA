"""Live voice configuration, built without opening audio or a provider connection."""

import pytest
from pydantic import ValidationError

from services.conversation import PERSONA, persona
from services.live_config import PREBUILT_VOICES, VOICE_LINE, make_live_config, voice_settings
from services.settings import SettingsPatch, SettingsService, SettingsStore


def test_push_to_talk_config_voice_compression_resumption_transcription_and_tools():
    config = make_live_config({})
    assert config.response_modalities == ["AUDIO"]
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Kore"
    assert config.input_audio_transcription is not None
    assert config.output_audio_transcription is not None
    assert config.context_window_compression.sliding_window is not None
    assert config.session_resumption is not None and config.session_resumption.handle is None
    assert config.realtime_input_config.automatic_activity_detection.disabled is True
    (tool,) = config.tools
    (brain,) = tool.function_declarations
    assert brain.name == "ask_brain" and brain.parameters.required == ["request"]
    # Live run (7 Nov 2026): Live refused a NAS 3D model itself; the description now names
    # what JARVIS's tools can do and forbids claiming it can't.
    assert "3D models and CAD parts" in brain.description
    for ability in ("images", "reminders", "phone calls", "files and projects", "smart devices",
                    "3D printers", "careful reasoning"):
        assert ability in brain.description
    assert "Never tell the owner JARVIS can't do something its tools might do; call ask_brain instead." in brain.description
    assert "in full" in brain.description and "One moment" in brain.description
    assert "approval on screen" in brain.description
    # Push-to-talk: the client marks turns, so no server tuning applies.
    detection = config.realtime_input_config.automatic_activity_detection
    assert detection.end_of_speech_sensitivity is None and detection.silence_duration_ms is None
    assert detection.prefix_padding_ms is None and detection.start_of_speech_sensitivity is None
    # The brain's stable persona plus exactly one spoken-style line.
    assert config.system_instruction == persona({}, VOICE_LINE)
    assert config.system_instruction.startswith(PERSONA)
    assert config.system_instruction.endswith(VOICE_LINE)
    assert config.max_output_tokens is None


def test_desktop_voice_pins_english_and_malay_but_calls_detect_any_language():
    # First live run (7 Nov 2026): with automatic detection a short "hello" became Spanish.
    from services.live_config import DESKTOP_LANGUAGES, declarations, live_connect_config

    for mode in ("push_to_talk", "conversation"):
        config = make_live_config({}, mode=mode)
        assert config.input_audio_transcription.language_codes == ["en-US", "ms-MY"]
    assert DESKTOP_LANGUAGES == ("en-US", "ms-MY")
    assert "Speak English; if the owner speaks Malay to you, answer in Malay." in VOICE_LINE
    # Phone calls share live_connect_config without the hint: callers may speak anything.
    call = live_connect_config(
        system_instruction="call", voice_name="Kore", function_declarations=declarations("conversation"),
        automatic_activity_detection=True,
    )
    assert not call.input_audio_transcription.language_codes


def test_conversation_waits_for_the_owner_to_finish_but_calls_keep_server_defaults():
    # Live run (7 Nov 2026): hands-free JARVIS answered on short pauses mid-sentence.
    from google.genai import types
    from services.live_config import declarations, live_connect_config

    detection = make_live_config({}, mode="conversation").realtime_input_config.automatic_activity_detection
    assert detection.disabled is False
    assert detection.end_of_speech_sensitivity == types.EndSensitivity.END_SENSITIVITY_LOW
    assert detection.silence_duration_ms == 1000 and detection.prefix_padding_ms == 300
    # Speakers reach the mic: a more eager start would make JARVIS interrupt itself.
    assert detection.start_of_speech_sensitivity is None
    call = live_connect_config(
        system_instruction="call", voice_name="Kore", function_declarations=declarations("conversation"),
        automatic_activity_detection=True,
    ).realtime_input_config.automatic_activity_detection
    assert call.disabled is False
    assert call.end_of_speech_sensitivity is None and call.start_of_speech_sensitivity is None
    assert call.silence_duration_ms is None and call.prefix_padding_ms is None


def test_conversation_config_resumes_with_handle_and_uses_the_chosen_voice():
    settings = {"voice": {"name": "Puck"}, "assistant": {"owner_name": "Hiro"}}
    config = make_live_config(settings, mode="conversation", handle="resume-1", max_output_tokens=512)
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
    assert config.session_resumption.handle == "resume-1"
    assert config.realtime_input_config.automatic_activity_detection.disabled is False
    assert config.realtime_input_config.activity_handling.value == "START_OF_ACTIVITY_INTERRUPTS"
    assert [item.name for item in config.tools[0].function_declarations] == [
        "ask_brain",
        "end_conversation",
    ]
    assert "Hiro" in config.system_instruction and config.max_output_tokens == 512
    with pytest.raises(ValueError):
        make_live_config({}, mode="wake_word")


def test_voice_settings_fall_back_and_patch_validates_documented_voices(tmp_path):
    assert len(PREBUILT_VOICES) == 30 and "Kore" in PREBUILT_VOICES
    assert voice_settings({"voice": {"name": "Robot", "mode": "always"}}) == {
        "name": "Kore",
        "mode": "push_to_talk",
    }
    for bad in ({"voice": {"name": "Robot"}}, {"voice": {"mode": "always"}}, {"voice": {}},
                {"voice": {"name": None}}, {"voice": {"name": "Kore", "pitch": 2}}):
        with pytest.raises(ValidationError):
            SettingsPatch.model_validate(bad)
    settings = {"tool_permissions": {}}
    service = SettingsService(settings, SettingsStore(tmp_path / "settings.json"), set())
    service.apply(SettingsPatch.model_validate({"voice": {"mode": "conversation"}}))
    # The "Hey Jarvis" and talking-overlay defaults.
    wake = {"wake_word": True, "wake_sensitivity": "normal", "overlay": True}
    assert settings["voice"] == {"name": "Kore", "mode": "conversation", **wake}
    service.apply(SettingsPatch.model_validate({"voice": {"name": "Aoede"}}))
    assert settings["voice"] == {"name": "Aoede", "mode": "conversation", **wake}
    assert voice_settings(settings) == {"name": "Aoede", "mode": "conversation"}
