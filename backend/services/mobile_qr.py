"""Optional offline SVG encoder. Invitation-file transfer works without this extra."""

import base64
import json


def invitation_qr(bundle):
    try:
        import qrcode
        from qrcode.image.svg import SvgPathFillImage
    except ImportError:
        return None
    image = qrcode.make(
        json.dumps(bundle, separators=(",", ":")), image_factory=SvgPathFillImage, border=4
    )
    raw = image.to_string()
    return base64.b64encode(raw).decode("ascii")
