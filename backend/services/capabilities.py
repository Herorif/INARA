"""Owner-only, on-demand readiness inspection. Never starts a provider or device."""

import importlib.util
import importlib.metadata
import time
from pydantic import ValidationError
from services.capability_profiles import WORKER_PROFILES, model_id, provider_key
from services.cad import blender_executable
from services.image_config import image_backend
from services.settings import EmptyRequest
from services.tools import ServiceError


class CapabilityCenter:
    def __init__(self, application):
        self.app = application
        application.sio.on("capability_diagnostics", handler=self.diagnostics)

    def snapshot(self, context):
        governor = self.app.resources
        hardware = governor.inspect_hardware()
        image = image_backend()
        key = bool(provider_key())
        try:
            importlib.metadata.version("google-genai")
            provider_installed = True
        except importlib.metadata.PackageNotFoundError:
            provider_installed = False
        image_installed = all(
            importlib.util.find_spec(name) is not None
            for name in ("torch", "diffusers", "transformers", "safetensors", "PIL")
        )
        blender = bool(blender_executable())
        descriptors = [
            ("cad_offline", "Parametric 3D", True, True, "Fixed offline geometry worker.", None),
            (
                "cad_blender",
                "Blender scenes",
                blender,
                blender,
                "Install Blender manually, then verify a scene.",
                None,
            ),
            (
                "text",
                "AI conversation & blueprints",
                provider_installed,
                key,
                "Set GEMINI_API_KEY when ready. Model availability is unverified.",
                model_id("text"),
            ),
            (
                "image_cpu",
                "Local image generation",
                image_installed,
                image.get("configured", False),
                image["reason"],
                image.get("model"),
            ),
            (
                "voice",
                "Reviewed push-to-talk",
                provider_installed,
                key,
                "Explicit prepare/hold/review/send. Microphone and transcription acceptance deferred.",
                model_id("speech"),
            ),
            (
                "camera",
                "Camera tracking",
                True,
                True,
                "Camera permission and real-device acceptance deferred.",
                None,
            ),
            (
                "android",
                "Android companion",
                False,
                False,
                "Pairing is planned for R7. Existing SIM and WhatsApp stay unchanged.",
                None,
            ),
        ]
        cards = []
        for identifier, title, installed, configured, reason, model in descriptors:
            profile = WORKER_PROFILES.get(identifier)
            blocked = None
            if governor.fault:
                blocked = governor.fault
            elif identifier != "text" and governor.state in ("resident", "gaming"):
                blocked = "Heavy work is paused in this resource mode."
            elif profile and configured:
                try:
                    governor.check_capacity(identifier)
                    if len(governor.reservations) >= governor.max_jobs:
                        blocked = "The creative queue is full. Cancel a job or wait."
                except ServiceError as exc:
                    blocked = str(exc)
            history = []
            if identifier in ("cad_offline", "cad_blender", "image_cpu"):
                service = self.app.images if identifier == "image_cpu" else self.app.cad
                history = [
                    job
                    for job in service.list(context["principal"], context["project_path"])
                    if job.get("resources", {}).get("profile") == identifier
                    and job["state"] == "succeeded"
                ]
            measured = next(
                (
                    job.get("duration_seconds")
                    for job in history
                    if job.get("duration_seconds") is not None
                ),
                None,
            )
            cards.append(
                {
                    "id": identifier,
                    "title": title,
                    "installed": installed,
                    "configured": configured,
                    "verified": bool(history),
                    "blocked": blocked,
                    "status": "setup_required"
                    if not configured or not installed
                    else "blocked"
                    if blocked
                    else "available",
                    "reason": reason,
                    "model": model,
                    "profile": profile,
                    "last_duration_seconds": measured,
                }
            )
        return {
            "checked_at": time.time(),
            "hardware": hardware,
            "resources": governor.snapshot(),
            "capabilities": cards,
            "profiles": {
                "local": "Fixed CPU creative workers",
                "cloud": "Explicit provider configuration required",
                "manual": "No automatic installation or resource escalation",
            },
        }

    async def diagnostics(self, sid, data=None):
        try:
            context = self.app.studio_context(sid)
            self.app.authorize_owner(context)
            EmptyRequest.model_validate({} if data is None else data)
            return {"ok": True, **self.snapshot(context)}
        except (ServiceError, ValidationError) as exc:
            return {
                "ok": False,
                "code": getattr(exc, "code", "invalid_arguments"),
                "message": str(exc)
                if isinstance(exc, ServiceError)
                else "Diagnostics accepts no fields.",
            }
        except Exception:
            return {
                "ok": False,
                "code": "diagnostics_failed",
                "message": "Diagnostics could not read the current state. Refresh to try again.",
            }
