"""Fixed local Diffusers adapter. Imported exclusively inside the owned image worker."""

import os


def generate(recipe, model_dir, progress):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    import torch
    import diffusers
    from services.image_config import inspect_model

    folder, pipeline_name = inspect_model(model_dir)
    torch.set_num_threads(2)
    # Fixed admitted image_cpu profile: GPU use requires separate acceptance.
    device = "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    progress("loading")
    pipeline = getattr(diffusers, pipeline_name).from_pretrained(
        str(folder), local_files_only=True, use_safetensors=True, torch_dtype=dtype
    )
    pipeline.to(device)
    pipeline.enable_vae_slicing()
    pipeline.set_progress_bar_config(disable=True)

    def step_end(pipe, index, timestep, kwargs):
        progress("generating")
        return kwargs

    progress("generating")
    with torch.inference_mode():
        output = pipeline(
            prompt=recipe["prompt"],
            negative_prompt=recipe["negative_prompt"],
            width=recipe["width"],
            height=recipe["height"],
            num_inference_steps=recipe["steps"],
            guidance_scale=recipe["guidance"],
            generator=torch.Generator(device=device).manual_seed(recipe["seed"]),
            callback_on_step_end=step_end,
        )
    if getattr(output, "nsfw_content_detected", None) and any(output.nsfw_content_detected):
        raise ValueError("The configured pipeline declined the result")
    return output.images[0], {
        "width": recipe["width"],
        "height": recipe["height"],
        "seed": recipe["seed"],
        "backend": "local_diffusers",
        "model": folder.name[:80],
        "device": device,
    }
