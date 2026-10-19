"""Owner-authorized compatibility operations. Optional adapters stay lazy."""

from services.printer_monitor import PrinterMonitor
from services.device_contracts import AddPrinter, KasaControl
from services.local_actions import NoArguments
from services.lazy import LazyService
from services.tools import ServiceError, ToolSpec


class DevicePrinterService:
    def __init__(self, dispatcher, sessions, settings_service, kasa, printer, publish):
        self.dispatcher, self.sessions, self.settings = dispatcher, sessions, settings_service
        self.kasa, self.printer, self.publish = kasa, printer, publish
        self.observation = PrinterMonitor(
            lambda owner: self.dispatcher.authenticated(owner) and bool(self.sessions.rooms(owner, "renderer")),
            publish,
        )
        for name, model, permission in (
            ("discover_kasa", NoArguments, None),
            ("control_kasa", KasaControl, "control_device"),
            ("discover_printers", NoArguments, None),
            ("add_printer", AddPrinter, None),
            ("get_slicer_profiles", NoArguments, None),
        ):
            dispatcher.register(
                ToolSpec(
                    name,
                    f"Local {name.replace('_', ' ')}.",
                    model,
                    self.execute(name),
                    execution_timeout=30,
                    permission=permission,
                    model_visible=name != "control_kasa",
                )
            )

    def authorize(self, context):
        principal = context["principal"]
        owner = (
            self.sessions.native_desktop.state.identity.owner
            if self.sessions.native_desktop
            else self.sessions.local_owner
        )
        if principal != owner or not self.dispatcher.authenticated(principal):
            raise ServiceError(
                "permission_denied", "Use the authenticated desktop owner for device setup."
            )

    def activate_printer(self, principal=None):
        fresh = isinstance(self.printer, LazyService) and self.printer.instance is None
        if fresh:
            self.printer.get()
            for item in self.settings.settings.get("printers", []):
                self.printer.add_printer_manually(
                    item.get("name", item["host"]),
                    item["host"],
                    port=item.get("port", 80),
                    printer_type=item.get("type", "moonraker"),
                    camera_url=item.get("camera_url"),
                )
        return self.printer

    def persist(self, key, values, identity):
        # Preserve saved devices that were not found in this particular scan.
        snapshot = self.settings.snapshot()
        merged = {identity(item): item for item in snapshot.get(key, [])}
        for item in values:
            merged[identity(item)] = {**merged.get(identity(item), {}), **item}
        snapshot[key] = list(merged.values())
        try:
            self.settings.store.save(snapshot)
        except Exception as exc:
            raise ServiceError(
                "settings_unavailable",
                "Device settings could not be saved; previous configuration was preserved.",
            ) from exc
        self.settings.settings[key] = snapshot[key]

    def start_monitor(self, owner):
        self.observation.start(owner, self.printer)

    async def close(self):
        await self.observation.close()

    def execute(self, name):
        async def run(args, context):
            self.authorize(context)
            owner = context["principal"]
            if name == "discover_kasa":
                devices = await self.kasa.discover_devices()
                saved = [{key: item[key] for key in ("ip", "alias", "model")} for item in devices]
                self.persist("kasa_devices", saved, lambda item: item["ip"])
                return {"devices": devices, "message": f"Found {len(devices)} Kasa devices"}
            if name == "control_kasa":
                request = args.root
                # This compatibility route cannot turn an arbitrary address into a new target.
                if request.ip not in self.kasa.devices:
                    raise ServiceError(
                        "device_missing",
                        "Discover or initialize this device before controlling it.",
                    )
                if request.action == "on":
                    ok = await self.kasa.turn_on(request.ip)
                elif request.action == "off":
                    ok = await self.kasa.turn_off(request.ip)
                elif request.action == "brightness":
                    ok = await self.kasa.set_brightness(request.ip, request.value)
                else:
                    ok = await self.kasa.set_color(
                        request.ip, (request.value.h, request.value.s, request.value.v)
                    )
                if not ok:
                    raise ServiceError(
                        "device_failed",
                        "Device control could not complete. Check device state before retrying.",
                    )
                return {
                    "ip": request.ip,
                    "is_on": request.action == "on" if request.action in ("on", "off") else None,
                    "brightness": request.value if request.action == "brightness" else None,
                }
            printer = self.activate_printer(owner)
            if name == "discover_printers":
                found = await printer.discover_printers()
                self.start_monitor(owner)
                return {
                    "printers": printer.get_printer_list(),
                    "system": printer.get_slicer_status(),
                    "message": f"Found {len(found)} printers",
                }
            if name == "get_slicer_profiles":
                return {
                    "profiles": printer.get_available_profiles(),
                    "system": printer.get_slicer_status(),
                }
            # Save an explicit endpoint/type; never silently probe and replace the approved endpoint.
            item = {
                "host": args.host,
                "port": args.port,
                "name": args.name or args.host,
                "type": args.type,
                "camera_url": args.camera_url,
            }
            self.persist("printers", [item], lambda value: (value["host"], value.get("port", 80)))
            printer.add_printer_manually(
                item["name"],
                args.host,
                port=args.port,
                printer_type=args.type,
                camera_url=args.camera_url,
            )
            self.start_monitor(owner)
            return {
                "printers": printer.get_printer_list(),
                "message": f"Added printer: {item['name']}",
            }

        return run
