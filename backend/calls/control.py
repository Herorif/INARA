"""Bounded stdin/stdout native adapter. No shell, guessed shortcuts or coordinates."""

import asyncio
import json
import os
from pathlib import Path
import subprocess

from services.tools import ServiceError
from calls.contracts import Observation


class DesktopControl:
    def __init__(self, helper, profile):
        self.helper, self.profile = Path(helper), profile

    async def request(self, operation, expected=None):
        if not self.helper.is_file():
            raise ServiceError("call_helper_missing", "Build the local call-control helper first.")
        payload = {"operation": operation, "profile": self.profile.model_dump()}
        if expected:
            payload["expected"] = expected.fingerprint
        process = await asyncio.create_subprocess_exec(
            str(self.helper), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            limit=65536,
        )
        try:
            output, _ = await asyncio.wait_for(
                process.communicate(json.dumps(payload).encode()), 5
            )
            if len(output) > 65536:
                raise ValueError("Oversized native response")
            result = json.loads(output)
            if process.returncode or not result.get("ok"):
                raise ValueError("Native control rejected the current binding")
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ServiceError(
                "call_control_unavailable", "The pinned call control is unavailable or changed."
            ) from exc
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def observe(self):
        result = await self.request("observe")
        return Observation.model_validate(result["observation"])

    async def answer(self, expected):
        await self.request("answer", expected)

    async def hangup(self, expected):
        await self.request("hangup", expected)
