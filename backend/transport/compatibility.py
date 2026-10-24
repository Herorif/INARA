"""Scoped compatibility wire events over the shared local-action request lifetime."""

from transport.local_actions import LocalActionTransport


class CompatibilityTransport(LocalActionTransport):
    events = (
        "discover_kasa",
        "control_kasa",
        "discover_printers",
        "add_printer",
        "get_slicer_profiles",
        "print_stl",
    )

    def context(self, sid):
        self.sessions.require_owner(sid, {"renderer"})
        return self.sessions.context(sid, renderer=True)

    async def emit_result(self, name, result, sid):
        if name == "discover_kasa":
            await self.sio.emit("kasa_devices", result["devices"], room=sid)
        elif name == "control_kasa":
            await self.sio.emit("kasa_update", result, room=sid)
        elif name in ("discover_printers", "add_printer"):
            if "system" in result:
                await self.sio.emit("printer_system_status", result["system"], room=sid)
            await self.sio.emit("printer_list", result["printers"], room=sid)
        elif name == "get_slicer_profiles":
            await self.sio.emit("printer_system_status", result["system"], room=sid)
            await self.sio.emit("slicer_profiles", result["profiles"], room=sid)
        elif name == "print_stl":
            await self.sio.emit("print_result", result, room=sid)
        if "message" in result:
            await self.sio.emit("status", {"msg": result["message"]}, room=sid)

    async def emit_error(self, name, sid, payload):
        if name == "print_stl":
            await self.sio.emit(
                "print_result",
                {"status": "error", "message": payload["msg"], "code": payload["code"]},
                room=sid,
            )
        await super().emit_error(name, sid, payload)
