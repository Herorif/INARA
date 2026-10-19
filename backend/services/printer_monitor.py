"""On-demand, owner-bound printer observation, separate from setup and control."""

import asyncio


class PrinterMonitor:
    def __init__(self, authorized, publish):
        self.authorized, self.publish = authorized, publish
        self.task = None

    def start(self, owner, printer):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.poll(owner, printer), name="printer-monitor")

    async def poll(self, owner, printer):
        while self.authorized(owner):
            for host in tuple(printer.printers):
                if not self.authorized(owner):
                    return
                if printer.should_poll_printer(host):
                    try:
                        async with asyncio.timeout(10):
                            status = await printer.get_print_status(host)
                        if status and self.authorized(owner):
                            await self.publish("print_status_update", owner, status.to_dict())
                    except Exception:
                        pass  # Adapter owns bounded backoff; never disclose raw network errors.
            await asyncio.sleep(2)

    async def close(self):
        task, self.task = self.task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
