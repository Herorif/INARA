"""Fixed launch/configuration profiles, safe to inspect without loading adapters."""

import os


RAM_HEADROOM_MB = 1024

# Gemini model ids. ``None`` follows the text model. Claude (the brain) model ids live
# in llm/router.py (INARA_BRAIN_MODEL / INARA_FAST_MODEL).
MODEL_DEFAULTS = {
    "speech": ("INARA_TRANSCRIPTION_MODEL", None),
    "text": ("INARA_TEXT_MODEL", "gemini-3.8-flash"),
    # Preview id: the provider lists its earliest shutdown as 17 Nov 2026
    # (docs/PROJECT_REVIEW.md). Replace it in the live-voice task.
    "voice": ("INARA_VOICE_MODEL", "models/gemini-2.5-flash-native-audio-preview-12-2025"),
    # gemini-2.0-flash and gemini-3-pro-preview are shut down, and Google's model list
    # (https://ai.google.dev/gemini-api/docs/models, checked 26 Oct 2026) has no stable
    # Pro model, so vision and legacy CAD follow the text model.
    "vision": ("INARA_VISION_MODEL", None),
    "legacy_cad": ("INARA_LEGACY_CAD_MODEL", None),
}


def model_id(capability):
    variable, default = MODEL_DEFAULTS[capability]
    return os.getenv(variable) or (model_id("text") if default is None else default)


# Admission estimates, not measured peaks or an OS memory sandbox. No automatic
# CPU->GPU escalation. Image CUDA support is held until hardware acceptance.
WORKER_PROFILES = {
    "call_local": {"cpu": 1, "ram_mb": 512, "vram_mb": 0, "device": "cpu"},
    "call_model": {"cpu": 2, "ram_mb": 6144, "vram_mb": 0, "device": "cpu"},
    "cad_offline": {"cpu": 2, "ram_mb": 512, "vram_mb": 0, "device": "cpu"},
    "cad_blender": {"cpu": 2, "ram_mb": 2048, "vram_mb": 0, "device": "cpu"},
    "image_cpu": {"cpu": 2, "ram_mb": 8192, "vram_mb": 0, "device": "cpu"},
    "verification_fixture": {"cpu": 1, "ram_mb": 256, "vram_mb": 0, "device": "fixture"},
}


def worker_profile(namespace, recipe, fixture=False):
    if fixture:
        return "verification_fixture"
    if namespace == "image_jobs:":
        return "image_cpu"
    return "cad_blender" if recipe.get("engine") == "blender" else "cad_offline"


def provider_key():
    """Gemini key: non-placeholder GEMINI_API_KEY override, else the encrypted store."""
    from services.secrets import resolve

    return resolve("gemini_api_key")


def anthropic_key():
    """Anthropic key: non-placeholder ANTHROPIC_API_KEY override, else the encrypted store."""
    from services.secrets import resolve

    return resolve("anthropic_api_key")
