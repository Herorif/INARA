"""
Smoke tests for the legacy desktop runtime in backend/server.py.

These tests use only the Python standard library so they can run even when
pytest is not installed in the active environment.
"""
import os
import shutil
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import server


class LegacyRuntimeSmokeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.emitted_events = []
        self.original_emit = server.sio.emit

        async def fake_emit(event, data=None, room=None):
            self.emitted_events.append({"event": event, "data": data, "room": room})

        server.sio.emit = fake_emit

    def tearDown(self):
        server.sio.emit = self.original_emit

    def test_status_summary_reports_invalid_api_key(self):
        """Status summary should flag placeholder Gemini keys as blocked."""
        previous_key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "your_api_key_here"

        try:
            summary = server.get_runtime_summary()
        finally:
            if previous_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = previous_key

        self.assertEqual(summary["runtime"], "legacy-desktop-backend")
        self.assertEqual(summary["entrypoint"], "backend/server.py")
        self.assertTrue(summary["ai_status"].startswith("blocked"))
        self.assertIn("placeholder", summary["ai_status"].lower())

    async def test_discover_kasa_emits_devices_and_persists_minimal_settings(self):
        """Kasa discovery should tolerate optional payloads and emit device data."""
        discovered_devices = [
            {
                "ip": "10.0.0.25",
                "alias": "Desk Lamp",
                "model": "KP125",
                "is_on": True,
            }
        ]
        original_kasa_devices = list(server.SETTINGS.get("kasa_devices", []))
        persisted_devices = None

        try:
            server.SETTINGS["kasa_devices"] = []
            with patch.object(server.kasa_agent, "discover_devices", AsyncMock(return_value=discovered_devices)):
                with patch.object(server, "save_settings", lambda: None):
                    await server.discover_kasa("client-1", None)
                    persisted_devices = list(server.SETTINGS["kasa_devices"])
        finally:
            server.SETTINGS["kasa_devices"] = original_kasa_devices

        self.assertEqual(self.emitted_events[0]["event"], "kasa_devices")
        self.assertEqual(self.emitted_events[0]["data"], discovered_devices)
        self.assertEqual(
            self.emitted_events[1],
            {
                "event": "status",
                "data": {"msg": "Found 1 Kasa devices"},
                "room": None,
            },
        )
        self.assertEqual(
            persisted_devices,
            [
                {
                    "ip": "10.0.0.25",
                    "alias": "Desk Lamp",
                    "model": "KP125",
                }
            ],
        )

    async def test_discover_printers_emits_status_and_printer_list(self):
        """Printer discovery should emit slicer status, printer list, and status text."""
        slicer_status = {
            "available": False,
            "path": None,
            "profiles_dir": None,
            "message": "Printing is unavailable until OrcaSlicer or PrusaSlicer is installed.",
        }
        printers = [
            {
                "name": "Creality K1",
                "host": "10.0.0.142",
                "port": 7125,
                "printer_type": "moonraker",
            }
        ]

        with patch.object(server.printer_agent, "get_slicer_status", lambda: slicer_status):
            with patch.object(server.printer_agent, "discover_printers", AsyncMock(return_value=printers)):
                with patch.object(server.printer_agent, "get_printer_list", lambda: printers):
                    await server.discover_printers("client-2", None)

        self.assertEqual(
            self.emitted_events[0],
            {
                "event": "printer_system_status",
                "data": slicer_status,
                "room": "client-2",
            },
        )
        self.assertEqual(
            self.emitted_events[1],
            {
                "event": "printer_list",
                "data": printers,
                "room": None,
            },
        )
        self.assertEqual(
            self.emitted_events[2],
            {
                "event": "status",
                "data": {"msg": "Found 1 printers"},
                "room": None,
            },
        )

    async def test_prompt_web_agent_uses_run_task_and_forwards_updates(self):
        """The legacy web prompt path should call run_task and forward UI updates."""
        update_payloads = []
        calls = {}
        testcase = self

        class FakeWebAgent:
            async def run_task(self, prompt, update_callback=None):
                calls["prompt"] = prompt
                testcase.assertIsNotNone(update_callback)
                await update_callback("image-123", "navigated")
                return {"ok": True}

        fake_audio_loop = SimpleNamespace(
            web_agent=FakeWebAgent(),
            on_web_data=update_payloads.append,
        )

        with patch.object(server, "audio_loop", fake_audio_loop):
            with patch.object(server, "get_ai_preflight_error", lambda: None):
                await server.prompt_web_agent("client-3", {"prompt": "search example.com"})

        self.assertEqual(calls["prompt"], "search example.com")
        self.assertEqual(update_payloads, [{"image": "image-123", "log": "navigated"}])
        self.assertEqual(
            self.emitted_events[0],
            {
                "event": "status",
                "data": {"msg": "Web Agent running..."},
                "room": None,
            },
        )
        self.assertEqual(
            self.emitted_events[1],
            {
                "event": "status",
                "data": {"msg": "Web Agent finished"},
                "room": None,
            },
        )

    async def test_save_memory_writes_conversation_to_disk(self):
        """save_memory should persist the provided transcript and emit success."""
        original_cwd = os.getcwd()
        temp_dir = Path(__file__).parent / ".tmp_legacy_runtime_smoke"

        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            os.chdir(temp_dir)
            await server.save_memory(
                "client-4",
                {
                    "filename": "session-notes",
                    "messages": [
                        {"sender": "User", "text": "Hello"},
                        {"sender": "INARA", "text": "Hi there"},
                    ],
                },
            )
            saved_file = temp_dir / "long_term_memory" / "session-notes.txt"
            self.assertTrue(saved_file.exists())
            self.assertEqual(
                saved_file.read_text(encoding="utf-8"),
                "User: Hello\nINARA: Hi there\n",
            )
        finally:
            os.chdir(original_cwd)
            shutil.rmtree(temp_dir, ignore_errors=True)

        self.assertEqual(
            self.emitted_events[-1],
            {
                "event": "status",
                "data": {"msg": "Memory Saved Successfully"},
                "room": None,
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
