"""Live configuration and device ownership without opening audio or providers."""

import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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


@pytest.fixture
def audio_class():
    # Compile the real constructor/lifecycle without importing optional media modules.
    source = Path("backend/inara.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AudioLoop")
    cls.body = [
        n
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and n.name in {"__init__", "close", "stop", "set_paused"}
    ]
    client, engine = Mock(), Mock()
    scope = {
        "DEFAULT_MODE": "camera",
        "asyncio": asyncio,
        "os": os,
        "make_live_config": Mock(return_value="generated-config"),
        "genai": SimpleNamespace(Client=Mock(return_value=client)),
        "pyaudio": SimpleNamespace(PyAudio=Mock(return_value=engine)),
    }
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "inara.py", "exec"), scope)
    return scope, client, engine


def test_audio_constructor_and_close_own_device_resources(audio_class):
    scope, client, engine = audio_class
    bridge, projects = object(), object()
    audio = scope["AudioLoop"](project_manager=projects, tool_bridge=bridge, video_mode="none")
    scope["make_live_config"].assert_called_once_with(bridge)
    assert audio.config == "generated-config" and audio.project_manager is projects
    audio.stop()
    assert audio.stop_event.is_set()
    audio.close()
    audio.close()
    client.close.assert_called_once()
    engine.terminate.assert_called_once()


def test_audio_device_failure_closes_provider_client(audio_class):
    scope, client, _ = audio_class
    scope["pyaudio"].PyAudio.side_effect = RuntimeError("device unavailable")
    with pytest.raises(RuntimeError, match="device unavailable"):
        scope["AudioLoop"](project_manager=object())
    client.close.assert_called_once()
