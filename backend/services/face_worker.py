"""Kill-on-close process ownership for the optional face/camera adapter."""

import asyncio
import json
from pathlib import Path
import sys
import uuid

from services.tools import ServiceError


class FaceWorker:
    def __init__(self, app, process_factory=None, timeout=120):
        self.app, self.process, self.folder = app, None, None
        self.process_factory, self.timeout = process_factory, timeout

    @staticmethod
    def reference(app):
        reference = Path(__file__).resolve().parents[1] / "reference.jpg"
        return (
            reference
            if reference.is_file()
            else app.projects.workspace_root.resolve() / "reference.jpg"
        )

    @classmethod
    def check_setup(cls, app):
        if (
            not (Path(__file__).resolve().parents[1] / "face_landmarker.task").is_file()
            or not cls.reference(app).is_file()
        ):
            raise ServiceError(
                "face_setup_required",
                "Install the local face model and reference image before enabling face verification.",
            )

    async def run(self, status, frame):
        from resident.win32 import WorkspaceProcess

        private = (self.app.database.directory / "face-sessions").resolve()
        private.mkdir(parents=True, exist_ok=True)
        self.folder = private / str(uuid.uuid4())
        self.folder.mkdir()
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        try:
            reference = self.reference(self.app)
            factory = self.process_factory or WorkspaceProcess
            self.process = factory(
                executable,
                Path(__file__).resolve().parents[1] / "workers/face_worker.py",
                {
                    "output": str(self.folder),
                    "reference": str(reference),
                },
                self.folder,
            )
            previous = None
            async with asyncio.timeout(self.timeout):
                while True:
                    report = self.folder / "state.json"
                    if report.is_file() and report.stat().st_size <= 600000:
                        try:
                            with report.open("rb") as stream:
                                raw = stream.read(600001)
                            data = json.loads(raw) if len(raw) <= 600000 else None
                        except (OSError, ValueError):
                            data = None
                        if isinstance(data, dict) and data and data != previous:
                            previous = data
                            if data.get("error"):
                                raise ServiceError(
                                    "face_unavailable",
                                    "Face setup is unavailable. Check the local model and reference image.",
                                )
                            if data.get("authenticated") is True:
                                await status(True)
                                return
                            image = data.get("frame")
                            if isinstance(image, str) and len(image) <= 550000:
                                await frame(image)
                    if not self.process.alive():
                        raise ServiceError(
                            "face_unavailable", "Face verification stopped before authentication."
                        )
                    await asyncio.sleep(0.1)
        finally:
            await self.close()

    async def close(self):
        if self.process:
            self.process.close()  # Job Object stops the entire owned camera process tree.
            self.process = None
        if self.folder:
            # Windows can retain the killed child's current-directory handle
            # briefly after the Job Object closes. Bound cleanup, never recurse.
            for _ in range(50):
                try:
                    for name in ("state.json", "state.tmp"):
                        (self.folder / name).unlink(missing_ok=True)
                    self.folder.rmdir()
                    return
                except FileNotFoundError:
                    return
                except OSError:
                    await asyncio.sleep(0.02)
            raise ServiceError(
                "face_cleanup_failed",
                "Face worker stopped, but its temporary directory could not be removed.",
            )
