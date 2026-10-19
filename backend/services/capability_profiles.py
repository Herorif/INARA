"""Fixed launch/configuration profiles, safe to inspect without loading adapters."""

import os


RAM_HEADROOM_MB = 1024

MODEL_DEFAULTS = {
    "text": ("INARA_TEXT_MODEL", "gemini-3.8-flash"),
    "voice": ("INARA_VOICE_MODEL", "models/gemini-2.5-flash-native-audio-preview-12-2025"),
    "vision": ("INARA_VISION_MODEL", "gemini-2.0-flash"),
    "browser": ("INARA_BROWSER_MODEL", "gemini-2.5-computer-use-preview-10-2025"),
    "legacy_cad": ("INARA_LEGACY_CAD_MODEL", "gemini-3-pro-preview"),
}


def model_id(capability):
    variable, default = MODEL_DEFAULTS[capability]
    return os.getenv(variable, default)


# Admission estimates, not measured peaks or an OS memory sandbox. No automatic
# CPU->GPU escalation. Image CUDA support is held until hardware acceptance.
WORKER_PROFILES = {
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
    value = os.getenv("GEMINI_API_KEY", "").strip()
    if value.lower() in {
        "",
        "your_api_key_here",
        "your_gemini_key",
        "your_gemini_api_key_here",
        "changeme",
    }:
        return None
    return value
