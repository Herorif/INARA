"""Bounded confirmation gate retained until voice tools use shared dispatch."""

import asyncio
import uuid


async def approve_voice(name, arguments, permissions, pending, callback, timeout=60):
    permission = "generate_cad" if name in ("generate_cad_prototype", "iterate_cad") else name

    def denied():
        return permissions.get(permission) == "deny" or permissions.get(name) == "deny"

    if denied():
        return False
    if permissions.get(permission, True) in (False, "allow_within_scope"):
        return True
    if callback is None:
        return False
    identifier = str(uuid.uuid4())
    future = asyncio.get_running_loop().create_future()
    pending[identifier] = future
    try:
        callback({"id": identifier, "tool": name, "args": arguments})
        try:
            confirmed = await asyncio.wait_for(future, timeout)
        except TimeoutError:
            return False
        return confirmed is True and not denied()
    finally:
        pending.pop(identifier, None)
