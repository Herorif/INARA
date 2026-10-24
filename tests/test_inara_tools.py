"""Live configuration and device ownership without opening audio or providers."""


import pytest

from services.live_config import make_live_config
from services.voice import VoiceBridge, VOICE_TARGETS


def test_live_config_uses_only_shared_catalog(application_factory):
    app = application_factory()
    bridge = VoiceBridge(app, {"project_path": app.projects.get_current_project_path()})
    config = make_live_config(bridge)
    declarations = config.tools[0].function_declarations
    assert {item.name for item in declarations} == set(VOICE_TARGETS)
    assert len(declarations) == len(VOICE_TARGETS)
    assert config.response_modalities == ["AUDIO"]
    assert config.input_audio_transcription is not None
    assert config.output_audio_transcription is not None
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Kore"
    assert make_live_config().tools == []


def test_retired_entrypoints_cannot_open_media():
    import sys
    from inara import AudioLoop
    from voice.pipeline import VoicePipeline
    from services.tools import ServiceError
    assert VoicePipeline is AudioLoop
    with pytest.raises(ServiceError, match="Quick assistant"):
        AudioLoop()
    for name in ("inara", "voice.pipeline", "voice"):
        sys.modules.pop(name, None)
