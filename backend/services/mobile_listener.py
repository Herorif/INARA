"""Opt-in private-address TLS listener. No port, discovery or certificate work at startup."""

import asyncio
from contextlib import contextmanager
import base64
import ipaddress
import os
import ssl
import socket
import secrets
import tempfile
from pathlib import Path
from services.tools import ServiceError


def private_host(host):
    try:
        value = ipaddress.IPv4Address(host)
        allowed = value.is_loopback or any(
            value in ipaddress.IPv4Network(network)
            for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        if not allowed:
            raise ValueError()
        return str(value)
    except ValueError as exc:
        raise ServiceError(
            "mobile_bind",
            "Use an exact private IPv4 address; wildcard/public listeners are disabled.",
        ) from exc


def certificate_identity(database, host):
    """Persist TLS private key only inside DPAPI-encrypted database payloads."""
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    with database.transaction() as db:
        saved = database.get(db, "mobile_tls_v1", host)
        if saved:
            cert = x509.load_pem_x509_certificate(saved["cert"].encode())
            if cert.not_valid_after_utc < datetime.now(timezone.utc) + timedelta(days=1):
                raise ServiceError(
                    "mobile_certificate",
                    "TLS identity expired. Revoke devices and rotate identity manually before pairing again.",
                )
            return saved
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "INARA paired laptop")])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host))]),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256())
        )
        saved = {
            "cert": cert.public_bytes(serialization.Encoding.PEM).decode(),
            "key": key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
            "certificate": base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode(),
        }
        database.put(db, "mobile_tls_v1", host, saved)
        return saved


class MobileListener:
    def __init__(self, service):
        self.service = service
        self.server = self.task = self.socket = None
        self.endpoint = self.certificate = None
        self.lock = asyncio.Lock()

    @property
    def running(self):
        return bool(self.server and self.server.started and self.task and not self.task.done())

    def snapshot(self):
        return {"enabled": self.running, "endpoint": self.endpoint if self.running else None}

    async def start(self, host, port):
        async with self.lock:
            if self.task:
                raise ServiceError(
                    "mobile_running", "Stop the listener before changing its address."
                )
            host = private_host(host)
            identity = certificate_identity(self.service.app.database, host)
            import uvicorn
            from transport.mobile_api import MobileAPI

            from cryptography.hazmat.primitives import serialization

            password = secrets.token_urlsafe(32)
            key = serialization.load_pem_private_key(identity["key"].encode(), password=None)
            temporary = {
                "cert": identity["cert"],
                "key": key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.BestAvailableEncryption(password.encode()),
                ).decode(),
            }
            files = []
            try:
                for field in ("key", "cert"):
                    fd, name = tempfile.mkstemp(
                        prefix="inara-tls-", dir=self.service.app.database.directory
                    )
                    files.append(Path(name))
                    with os.fdopen(fd, "w", encoding="ascii") as stream:
                        stream.write(temporary[field])
                config = uvicorn.Config(
                    MobileAPI(self.service).app,
                    host=host,
                    port=port,
                    ssl_keyfile=str(files[0]),
                    ssl_keyfile_password=password,
                    ssl_certfile=str(files[1]),
                    ssl_version=ssl.PROTOCOL_TLS_SERVER,
                    proxy_headers=False,
                    access_log=False,
                    log_level="warning",
                    lifespan="off",
                    limit_concurrency=8,
                    timeout_keep_alive=2,
                    timeout_graceful_shutdown=3,
                )
                config.load()
            finally:
                for path in files:
                    path.unlink(missing_ok=True)
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.bind((host, port))
                self.socket.listen(8)
                self.socket.setblocking(False)
            except OSError as exc:
                if self.socket:
                    self.socket.close()
                self.socket = None
                raise ServiceError("mobile_listener", "Address or port is unavailable.") from exc

            class EmbeddedServer(uvicorn.Server):
                @contextmanager
                def capture_signals(self):
                    # The main desktop server owns process shutdown signals.
                    yield

            self.server = EmbeddedServer(config)
            self.endpoint = f"https://{host}:{port}"
            self.certificate = identity["certificate"]
            self.task = asyncio.create_task(
                self.server.serve(sockets=[self.socket]), name="mobile-tls-listener"
            )
            try:
                for _ in range(60):
                    if self.running:
                        return
                    if self.task.done():
                        break
                    await asyncio.sleep(0.05)
                raise ServiceError("mobile_listener", "Private TLS listener could not start.")
            except BaseException:
                await self._stop()
                raise

    async def stop(self):
        async with self.lock:
            await self._stop()

    async def _stop(self):
        if self.server:
            self.server.should_exit = True
        if self.task:
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 5)
            except (TimeoutError, asyncio.CancelledError):
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
        if self.socket:
            self.socket.close()
        self.server = self.task = self.socket = None
        self.endpoint = self.certificate = None
        self.service.challenge = None
        self.service.pending.clear()
