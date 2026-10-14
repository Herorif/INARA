"""Image-specific RPC contract; ownership and permissions use the shared transport."""

from services.creative_transport import CreativeTransport
from services.images import ImageRequest, ImageArtifactRequest


class ImageTransport(CreativeTransport):
    prefix = "image"
    tool = "generate_image"
    request_model = ImageRequest
    artifact_model = ImageArtifactRequest

    def capabilities(self):
        return self.service.capabilities()
