"""Explicit test adapter; production services reject fixture provenance."""

from services.images import ImageService


class FixtureImageService(ImageService):
    worker_script = "../tests/fixtures/image_worker.py"
    expected_backend = "verification_fixture"
    enabled = True

    def capabilities(self):
        return {
            "available": self.enabled,
            "backend": "verification_fixture",
            "model": "VERIFICATION FIXTURE - NO MODEL RAN",
            "reason": "Verification fixture only. No image model runs in this test."
            if self.enabled
            else "Model setup deferred. No local image model is configured.",
        }

    def admit(self, recipe):
        if not self.enabled:
            return super().admit(recipe)
        return {}

    def bootstrap(self, staging, recipe, backend):
        return {"staging": str(staging), "recipe": recipe}
