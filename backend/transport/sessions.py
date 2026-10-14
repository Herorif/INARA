"""Desktop session identity and request-scoped project snapshots.

This is the local desktop contract, not a mobile pairing or grants protocol.
"""

import hmac
import uuid
from dataclasses import dataclass
from pathlib import Path

from services.tools import ServiceError


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

    def accept(self, sid, auth, token=None):
        auth = auth if isinstance(auth, dict) else {}
        if token and not hmac.compare_digest(
            str(auth.get("token", "")).encode("utf-8"), token.encode("utf-8")
        ):
            return False
        try:
            principal = str(uuid.UUID(auth["client_id"])) if auth.get("client_id") else sid
        except (ValueError, TypeError, AttributeError):
            return False
        native = self.native_desktop
        if native and native.state.identity.owner and principal != native.state.identity.owner:
            return False
        self.principals[sid] = principal
        self.roles[sid] = (
            auth.get("role") if auth.get("role") in ("resident", "workspace") else "renderer"
        )
        return True

    def attach_native(self, owner):
        self.principals["native-resident"] = owner
        self.roles["native-resident"] = "resident"

    def authenticated(self, principal):
        return principal in self.principals.values() and (
            not self.settings.get("face_auth_enabled") or self.face_authenticated()
        )

    def context(self, sid, *, renderer=False):
        principal = self.principals.get(sid)
        if principal is None or (renderer and self.roles.get(sid) != "renderer"):
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
