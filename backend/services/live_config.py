"""Live voice configuration built from the shared catalog, without opening devices."""


def make_live_config(bridge=None):
    from google.genai import types

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        # We switch these from [] to {} to enable them with default settings
        output_audio_transcription={},
        input_audio_transcription={},
        system_instruction="Your name is INARA  - It's Not A Random Acronym. "
        "You are a composed, slightly dry, butler-style AI assistant. "
        "Your creator is Herorif, and you address him as 'Sir'. "
        "When answering, respond using complete and concise sentences to keep a quick pacing and keep the conversation flowing. "
        "You are capable, direct, and quietly confident.",
        tools=[{"function_declarations": bridge.schemas()}] if bridge else [],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        ),
    )
