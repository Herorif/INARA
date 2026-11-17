"""Owner-only routes for skills (S5.2, docs/SKILLS.md).

- ``skills_list``: every loaded skill ``[{slug, name, description, source, path, scripts}]``
  sorted by slug; ``source`` is "yours" (the owner's folder) or "built-in" (shipped).
- ``skills_delete`` {slug}: deletes one of the owner's skills (never a built-in one).

Every route needs the authenticated, unlocked desktop owner renderer. Answers are
``{ok: true, ...}`` or ``{ok: false, code, message}``. Names, descriptions and instructions
are never logged.
"""

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from services.log import get_logger
from services.settings import EmptyRequest
from services.skills import SLUG_PATTERN
from services.tools import ServiceError

logger = get_logger(__name__)


class SkillSlugRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: StrictStr = Field(pattern=SLUG_PATTERN)


class SkillsTransport:
    models = {
        "skills_list": EmptyRequest,
        "skills_delete": SkillSlugRequest,
    }

    def __init__(self, app):
        self.app = app
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    @property
    def service(self):
        return self.app.skills

    def handler(self, name, model):
        method = getattr(self, "_" + name)

        async def handle(sid, data=None):
            try:
                self.app.sessions.require_owner(sid, {"renderer"})
                request = model.model_validate({} if data is None else data)
                return await method(request)
            except ServiceError as exc:
                return {"ok": False, "code": exc.code, "message": str(exc)}
            except ValidationError:
                return {"ok": False, "code": "invalid_arguments",
                        "message": "That skill request isn't valid."}
            except Exception as exc:
                logger.warning("Skill request %s failed (%s)", name, type(exc).__name__)
                return {"ok": False, "code": "skills_unavailable",
                        "message": "Skills couldn't be read or changed. Try again."}

        return handle

    async def _skills_list(self, request):
        return {"ok": True, "skills": self.service.list()}

    async def _skills_delete(self, request):
        return {"ok": True, "deleted": self.service.delete(request.slug)}
