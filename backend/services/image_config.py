"""Cheap image configuration inspection; no tensor/model imports in the resident."""

import importlib.util
import json
import os
from pathlib import Path

PIPELINES = {"StableDiffusionPipeline", "StableDiffusionXLPipeline"}
COMPONENTS = {
    "vae": {("diffusers", "AutoencoderKL")},
    "unet": {("diffusers", "UNet2DConditionModel")},
    "text_encoder": {("transformers", "CLIPTextModel")},
    "text_encoder_2": {("transformers", "CLIPTextModelWithProjection")},
    "tokenizer": {("transformers", "CLIPTokenizer")},
    "tokenizer_2": {("transformers", "CLIPTokenizer")},
    "scheduler": {
        ("diffusers", name)
        for name in [
            "PNDMScheduler",
            "DDIMScheduler",
            "EulerDiscreteScheduler",
            "EulerAncestralDiscreteScheduler",
            "DPMSolverMultistepScheduler",
            "LMSDiscreteScheduler",
            "DDPMScheduler",
        ]
    },
    "safety_checker": {("stable_diffusion", "StableDiffusionSafetyChecker"), (None, None)},
    "feature_extractor": {("transformers", "CLIPImageProcessor"), (None, None)},
    "image_encoder": {(None, None)},
}


def inspect_model(directory):
    folder = Path(directory).resolve()
    path = folder / "model_index.json"
    with path.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("Model metadata limit")
    index = json.loads(raw)
    if not isinstance(index, dict) or index.get("_class_name") not in PIPELINES:
        raise ValueError("Unsupported pipeline")
    required = {"vae", "unet", "text_encoder", "tokenizer", "scheduler"}
    if index["_class_name"] == "StableDiffusionXLPipeline":
        required |= {"text_encoder_2", "tokenizer_2"}
    if not required <= index.keys():
        raise ValueError("Missing model components")
    for key, value in index.items():
        if key in COMPONENTS:
            if (
                not isinstance(value, list)
                or len(value) != 2
                or tuple(value) not in COMPONENTS[key]
            ):
                raise ValueError("Unsupported model component")
        elif key not in {
            "_class_name",
            "_diffusers_version",
            "_name_or_path",
            "requires_safety_checker",
            "force_zeros_for_empty_prompt",
            "add_watermarker",
        }:
            raise ValueError("Unsupported model metadata")
    return folder, index["_class_name"]


def image_backend():
    value = os.getenv("INARA_IMAGE_MODEL_DIR", "").strip()
    if not value:
        return {
            "available": False,
            "configured": False,
            "backend": "local_diffusers",
            "reason": "Model setup deferred. No local image model is configured.",
        }
    try:
        folder, pipeline = inspect_model(value)
        missing = [
            name
            for name in ("torch", "diffusers", "transformers", "safetensors", "PIL")
            if importlib.util.find_spec(name) is None
        ]
        if missing:
            return {
                "available": False,
                "backend": "local_diffusers",
                "reason": "The optional image-worker dependencies are not installed.",
                "configured": True,
            }
        return {
            "available": True,
            "configured": True,
            "backend": "local_diffusers",
            "model": folder.name,
            "pipeline": pipeline,
            "model_dir": str(folder),
            "reason": "Local configuration detected. Weights load only when you generate.",
        }
    except (OSError, ValueError, TypeError):
        return {
            "available": False,
            "configured": False,
            "backend": "local_diffusers",
            "reason": "The local model folder is missing or uses an unsupported pipeline.",
        }
