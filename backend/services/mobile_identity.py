"""Standard P-256 signatures and owner-protected durable identities/replay ledger."""

import base64
import hashlib
import time
from services.tools import ServiceError


def decode_key(value):
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        raw = base64.b64decode(value, validate=True)
        key = load_der_public_key(raw)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("P-256 required")
        return key, hashlib.sha256(raw).hexdigest()
    except Exception as exc:
        raise ServiceError("mobile_key", "Use a valid device P-256 public key.") from exc


def signing_bytes(path, device_id, request_id, timestamp, payload):
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return (
        f"INARA-MOBILE-1\nPOST\n{path}\n{device_id}\n{request_id}\n{timestamp}\n{digest}".encode()
    )


def verify(key, envelope, path, now):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    if abs(now - envelope.timestamp) > 30:
        raise ServiceError(
            "mobile_clock", "Request expired. Check device time and retry explicitly."
        )
    try:
        key.verify(
            base64.b64decode(envelope.signature, validate=True),
            signing_bytes(
                path, envelope.device_id, envelope.request_id, envelope.timestamp, envelope.payload
            ),
            ec.ECDSA(hashes.SHA256()),
        )
    except Exception as exc:
        raise ServiceError("mobile_auth", "Device authentication failed.") from exc


class MobileIdentities:
    kind = "mobile_device_v1"

    def __init__(self, database, clock=time.time):
        self.database, self.clock = database, clock

    def list(self):
        with self.database.connection() as db:
            return self.database.all(db, self.kind)

    def get(self, device_id):
        with self.database.connection() as db:
            return self.database.get(db, self.kind, str(device_id))

    def save(self, value):
        with self.database.transaction() as db:
            self.database.put(db, self.kind, value["device_id"], value)

    def consume(self, device_id, request_id):
        """Transactionally remember signed request IDs across process death."""
        now = self.clock()
        with self.database.transaction() as db:
            saved = self.database.get(db, "mobile_replay_v1", device_id) or {
                "seen_at": now,
                "requests": {},
            }
            if now < saved["seen_at"] - 30:
                raise ServiceError(
                    "mobile_clock", "Laptop clock moved backwards. Correct it before reconnecting."
                )
            value = saved["requests"]
            value = {key: expiry for key, expiry in value.items() if expiry > now}
            if request_id in value:
                raise ServiceError("mobile_replay", "This signed request was already used.")
            if len(value) >= 256:
                raise ServiceError("mobile_rate", "Too many requests. Wait before refreshing.")
            value[request_id] = now + 90
            self.database.put(
                db,
                "mobile_replay_v1",
                device_id,
                {"seen_at": max(now, saved["seen_at"]), "requests": value},
            )
