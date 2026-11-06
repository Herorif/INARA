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
    assert "files/projects/reminders/devices" in brain.description
    # The brain's stable persona plus exactly one spoken-style line.
    assert config.system_instruction == persona({}, VOICE_LINE)
    assert config.system_instruction.startswith(PERSONA)
    assert config.system_instruction.endswith(VOICE_LINE)
    assert config.max_output_tokens is None


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
