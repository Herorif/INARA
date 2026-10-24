"""Desktop owner controls for opt-in listener, invitations, approval and revocation."""

import asyncio
from pydantic import ValidationError
from services.mobile_contracts import (
    ListenerRequest,
    PairRequest,
    PairDecision,
    DeviceRequest,
    MobileEmpty,
)
from services.tools import ServiceError
from services.notifications import NotificationPolicy


class MobileTransport:
    models = {
        "mobile_state": MobileEmpty,
        "notification_inbox": DeviceRequest,
        "notification_policy": NotificationPolicy,
        "notification_clear": DeviceRequest,
        "mobile_listener": ListenerRequest,
        "mobile_pair": PairRequest,
        "mobile_pair_cancel": MobileEmpty,
        "mobile_decide": PairDecision,
        "mobile_revoke": DeviceRequest,
    }

    def __init__(self, app):
        self.app = app
        self.pending = {}
        for name, model in self.models.items():
            app.sio.on(name, handler=self.handler(name, model))

    def handler(self, name, model):
        async def handle(sid, data=None):
            task = asyncio.current_task()
            try:
                owner = self.app.sessions.require_owner(sid, {"renderer"})
                args = model.model_validate(data)
                self.pending[task] = sid
                if name.startswith("notification_"):
                    service = self.app.mobile.notifications
                    project = self.app.projects.get_current_project_path()
                    if name == "notification_policy":
                        result = service.configure(owner, project, args)
                    elif name == "notification_clear":
                        result = service.clear(owner, project, args.device_id)
                    else:
                        result = service.view(owner, project, args.device_id)
                    return {"ok": True, **result}
                if name == "mobile_listener":
                    if args.enabled:
                        try:
                            await self.app.mobile.listener.start(args.host, args.port)
                            self.app.sessions.require_owner(sid, {"renderer"})
                        except BaseException:
                            await self.app.mobile.listener.stop()
                            raise
                    else:
                        await self.app.mobile.stop_requests()
                        await self.app.mobile.listener.stop()
                elif name == "mobile_pair":
                    bundle = self.app.mobile.pair(
                        owner, self.app.projects.get_current_project_path(), args.allow_chat, args.allow_calls
                    )
                    from services.mobile_qr import invitation_qr

                    return {"ok": True, "invitation": bundle, "qr_svg": invitation_qr(bundle)}
                elif name == "mobile_decide":
                    self.app.mobile.decide(owner, args.device_id, args.approved)
                elif name == "mobile_pair_cancel":
                    self.app.mobile.challenge = None
                    self.app.mobile.pending.clear()
                elif name == "mobile_revoke":
                    await self.app.mobile.revoke(owner, args.device_id)
                self.app.sessions.require_owner(sid, {"renderer"})
                return {"ok": True, **self.app.mobile.snapshot(owner)}
            except (ServiceError, ValidationError) as exc:
                return {
                    "ok": False,
                    "code": getattr(exc, "code", "invalid_arguments"),
                    "message": str(exc)
                    if isinstance(exc, ServiceError)
                    else "Invalid companion request.",
                }
            except Exception:
                return {
                    "ok": False,
                    "code": "mobile_failed",
                    "message": "Companion action could not complete.",
                }
            finally:
                self.pending.pop(task, None)

        return handle

    async def stop_sid(self, sid=None):
        tasks = [
            task
            for task, origin in tuple(self.pending.items())
            if (sid is None or origin == sid) and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
