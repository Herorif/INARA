"""Compatibility entry point for the separately approved physical start stage."""

from devices.printer_protocols import PrinterProtocolClient


async def start_uploaded(printer, filename, client_factory=None):
    client = (
        PrinterProtocolClient()
        if client_factory is None
        else PrinterProtocolClient(sessions=lambda timeout: client_factory())
    )
    return await client.start(printer, filename)
