"""Voice previews with a fake TTS synthesizer: no network, key or speaker."""

import asyncio
import base64
from datetime import date
import io
import wave

import pytest
from google.genai import errors, types

from llm.pricing import estimate_microusd
from services.live_config import PREBUILT_VOICES
from services.voice_preview import PREVIEW_LINE, VoicePreviewRequest, extract_audio, map_error


def tts_response(pcm=b"\x01\x00" * 2400, *, wav=True, rate=24000, usage=True):
    if wav:
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(rate)
            audio.writeframes(pcm)
        data, mime = stream.getvalue(), "audio/wav"
    else:
        data, mime = pcm, f"audio/L16;codec=pcm;rate={rate}"
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part(inline_data=types.Blob(data=data, mime_type=mime))],
                )
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=80, total_token_count=90
        )
        if usage
        else None,
    )


class FakeSynth:
    def __init__(self, response=None, fail=None):
        self.calls = []
        self.response = response or tts_response()
        self.fail = fail

    async def __call__(self, model, name, max_output_tokens=None):
        self.calls.append((model, name, max_output_tokens))
        await asyncio.sleep(0)
        if self.fail:
            raise self.fail
        return self.response


@pytest.fixture
def preview(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner", "tray": "owner", "intruder": "stranger"})
    app.sessions.roles.update({"client": "renderer", "tray": "resident", "intruder": "renderer"})
    synth = FakeSynth()
    app.voice_preview.synthesizer = synth
    app.voice_preview.preflight = lambda: None
    return app, synth


def handler(app):
    return app.sio.handlers["/"]["voice_preview"]


def receipts(app):
    project = app.projects.get_current_project_path().resolve()
    return [
        item
        for item in app.usage.snapshot("owner", project)["records"]
        if item["feature"] == "voice_preview"
    ]


@pytest.mark.asyncio
async def test_preview_returns_pcm_and_caches_per_voice(preview):
    app, synth = preview
    first = await handler(app)("client", {"name": "Kore"})
    assert first["ok"] and first["name"] == "Kore" and not first["cached"]
    assert first["sample_rate"] == 24000
    assert base64.b64decode(first["pcm_base64"]) == b"\x01\x00" * 2400
    again = await handler(app)("client", {"name": "Kore"})
    assert again["ok"] and again["cached"] and again["pcm_base64"] == first["pcm_base64"]
    await handler(app)("client", {"name": "Despina"})
    assert [call[1] for call in synth.calls] == ["Kore", "Despina"]
    assert synth.calls[0][0] == "gemini-3.8-flash-tts"


@pytest.mark.asyncio
async def test_concurrent_previews_of_one_voice_make_one_request(preview):
    app, synth = preview
    results = await asyncio.gather(*(handler(app)("client", {"name": "Leda"}) for _ in range(3)))
    assert all(item["ok"] for item in results)
    assert len(synth.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data", [{"name": "Nova"}, {"name": "kore"}, {}, None, {"name": "Kore", "x": 1}, ["Kore"]]
)
async def test_unknown_voice_names_are_rejected_before_any_request(preview, data):
    app, synth = preview
    result = await handler(app)("client", data)
    assert result == {
        "ok": False,
        "code": "invalid_arguments",
        "message": "Choose one of the listed voices.",
    }
    assert not synth.calls and not receipts(app)


def test_request_accepts_exactly_the_documented_voices():
    for name in PREBUILT_VOICES:
        assert VoicePreviewRequest(name=name).name == name
    assert len(PREBUILT_VOICES) == 30


@pytest.mark.asyncio
@pytest.mark.parametrize("sid", ["unknown", "tray", "intruder", "locked"])
async def test_preview_is_owner_renderer_only(preview, sid):
    app, synth = preview
    if sid == "locked":
        sid = "client"
        app.settings["face_auth_enabled"] = True
    result = await handler(app)(sid, {"name": "Kore"})
    assert not result["ok"]
    assert result["code"] in {"authentication_required", "permission_denied"}
    assert not synth.calls


@pytest.mark.asyncio
async def test_no_gemini_key_is_provider_not_configured(preview, monkeypatch):
    import services.voice_preview as module

    app, synth = preview
    app.voice_preview.preflight = module.ready
    monkeypatch.setattr(module, "provider_key", lambda: None)
    result = await handler(app)("client", {"name": "Kore"})
    assert result == {
        "ok": False,
        "code": "provider_not_configured",
        "message": "Add a Gemini key to preview voices.",
    }
    assert not synth.calls and not receipts(app)


@pytest.mark.asyncio
async def test_preview_writes_a_priced_usage_receipt(preview):
    app, _ = preview
    await handler(app)("client", {"name": "Kore"})
    (receipt,) = receipts(app)
    assert receipt["state"] == "completed" and receipt["model"] == "gemini-3.8-flash-tts"
    assert receipt["tokens"]["input_tokens"] == 10 and receipt["tokens"]["output_tokens"] == 80
    assert receipt["estimated_cost_microusd"] == estimate_microusd(
        "gemini-3.8-flash-tts", receipt["tokens"]
    )
    project = app.projects.get_current_project_path().resolve()
    assert "voice_preview" in app.usage.snapshot("owner", project)["coverage"]
    # A cached repeat makes no request and no receipt.
    await handler(app)("client", {"name": "Kore"})
    assert len(receipts(app)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fail, code",
    [
        (errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid."}}), "provider_key_invalid"),
        (errors.ClientError(403, {"error": {"status": "PERMISSION_DENIED", "message": "x"}}), "provider_key_invalid"),
        (errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "x"}}), "provider_rate_limited"),
        (errors.ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "x"}}), "provider_unavailable"),
        (errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT", "message": "secret detail"}}), "provider_failed"),
        (asyncio.TimeoutError(), "provider_timeout"),
        (ConnectionError("down"), "provider_network"),
    ],
)
async def test_provider_failures_are_mapped_and_not_cached(preview, fail, code):
    app, synth = preview
    synth.fail = fail
    result = await handler(app)("client", {"name": "Kore"})
    assert not result["ok"] and result["code"] == code
    assert "secret detail" not in result["message"]
    (receipt,) = receipts(app)
    assert receipt["state"] == "uncertain"
    synth.fail = None
    assert (await handler(app)("client", {"name": "Kore"}))["ok"]
    assert len(synth.calls) == 2


def test_raw_pcm_responses_use_the_mime_rate():
    rate, pcm = extract_audio(tts_response(b"\x02\x00" * 10 + b"\x03", wav=False, rate=16000))
    assert rate == 16000 and pcm == b"\x02\x00" * 10


def test_responses_without_audio_fail_plainly():
    empty = types.GenerateContentResponse(candidates=[])
    with pytest.raises(Exception) as error:
        extract_audio(empty)
    assert error.value.code == "provider_failed"
    assert map_error(ValueError("boom")).code == "provider_failed"


def test_tts_price_table_and_cutover():
    counts = {"input_tokens": 10, "output_tokens": 80}
    # 10 * 0.50 + 80 * 9.00 micro-USD before 2027; 10 * 1.00 + 80 * 18.00 after.
    assert estimate_microusd("gemini-3.8-flash-tts", counts, today=date(2026, 10, 27)) == 725
    assert estimate_microusd("gemini-3.8-flash-tts", counts, today=date(2027, 1, 1)) == 1450
    assert estimate_microusd("models/gemini-3.8-flash-lite-tts", counts, today=date(2026, 12, 31)) == 485
    assert estimate_microusd("gemini-3.1-flash-tts-preview", counts) == 1610
    assert estimate_microusd("gemini-3.8-flash-tts", None) is None


def test_preview_line_is_fixed():
    assert PREVIEW_LINE == "Hello, I'm JARVIS. How can I help?"


def test_renderer_voice_descriptors_match_live_config():
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "src/features/settings/voiceSettingsModel.js"
    ).read_text(encoding="utf-8")
    block = source.split("export const VOICE_DESCRIPTORS = {", 1)[1].split("};", 1)[0]
    assert re.findall(r"(\w+): '", block) == list(PREBUILT_VOICES)
