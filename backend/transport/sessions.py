"""Desktop session identity and request-scoped project snapshots.

This is the local desktop contract, not a mobile pairing or grants protocol.
"""

import hmac
import uuid
from dataclasses import dataclass
from pathlib import Path

from services.tools import ServiceError


# Socket roles besides "renderer" (the default). "overlay" is the tray voice window (J4):
# it receives only voice_overlay / voice_level and may send only overlay_stop / overlay_open.
ROLES = ("resident", "workspace", "overlay")


@dataclass(frozen=True)
class RequestContext:
    principal: str
    project_path: Path
    project: str

    def tools(self):
        return {"principal": self.principal, "project_path": self.project_path}


class DesktopSessions:
    def __init__(self, projects, settings, face_authenticated):
        self.projects = projects
        self.settings = settings
        self.face_authenticated = face_authenticated
        self.principals = {}
        self.roles = {}
        self.native_desktop = None
        self.local_owner = None

    def accept(self, sid, auth, token):
        """Fail closed: no configured token, or a missing/wrong presented token, rejects."""
        auth = auth if isinstance(auth, dict) else {}
        presented = auth.get("token")
        if not (isinstance(token, str) and token and isinstance(presented, str)):
            return False
        if not hmac.compare_digest(presented.encode("utf-8"), token.encode("utf-8")):
            return False
        try:
            principal = str(uuid.UUID(auth["client_id"])) if auth.get("client_id") else sid
        except (ValueError, TypeError, AttributeError):
            return False
        native = self.native_desktop
        if native and native.state.identity.owner and principal != native.state.identity.owner:
            return False
        role = auth.get("role")
        role = role if role in ROLES else "renderer"
        # The talking overlay (J4) is only ever the registered owner's: it never registers
        # or pins an owner, and it is never a renderer.
        if role == "overlay" and not self.is_owner(principal):
            return False
        # Only a holder of this launch's token reaches here; there is no tokenless owner path.
        if self.local_owner is None:
            self.local_owner = principal
        self.principals[sid] = principal
        self.roles[sid] = role
        return True

    def attach_native(self, owner):
        self.local_owner = owner
        self.principals["native-resident"] = owner
        self.roles["native-resident"] = "resident"

    def authenticated(self, principal):
        return principal in self.principals.values() and (
            not self.settings.get("face_auth_enabled") or self.face_authenticated()
        )

    def context(self, sid, *, renderer=False):
        principal = self.principals.get(sid)
        role = self.roles.get(sid)
        # The overlay shows a voice session; it never acts with the owner's request context.
        if principal is None or role == "overlay" or (renderer and role != "renderer"):
            raise ServiceError(
                "authentication_required", "Use the connected workspace to access Studio."
            )
        return RequestContext(
            principal,
            self.projects.get_current_project_path().resolve(),
            self.projects.current_project,
        )

    def rooms(self, principal, role=None):
        return tuple(
            sid
            for sid, owner in tuple(self.principals.items())
            if owner == principal and (role is None or self.roles.get(sid) == role)
        )

    def remove(self, sid):
        role = self.roles.pop(sid, None)
        return self.principals.pop(sid, sid), role

    def require_owner(self, sid, roles, *, allow_locked=False, allow_registration=False):
        principal = self.principals.get(sid)
        if principal is None or self.roles.get(sid) not in roles:
            raise ServiceError("authentication_required", "Use the authorized desktop channel.")
        native = self.native_desktop
        owner = native.state.identity.owner if native else self.local_owner
        if owner is None and not (native and allow_registration):
            raise ServiceError("permission_denied", "Register the desktop owner first.")
        if owner is not None and principal != owner:
            raise ServiceError("permission_denied", "This action belongs to the desktop owner.")
        if not allow_locked and not self.authenticated(principal):
            raise ServiceError(
                "authentication_required", "Unlock JARVIS before changing desktop settings."
            )
        return principal

    def is_owner(self, principal):
        native = self.native_desktop
        owner = native.state.identity.owner if native else self.local_owner
        return owner is not None and principal == owner
