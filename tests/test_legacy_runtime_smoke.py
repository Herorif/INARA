"""
Smoke tests for the legacy desktop runtime in backend/server.py.

These tests use only the Python standard library so they can run even when
pytest is not installed in the active environment.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

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

    def test_archived_core_server_requires_explicit_override(self):
        """The archived core server should not be runnable by accident."""
        env = os.environ.copy()
        env.pop("INARA_ALLOW_EXPERIMENTAL_CORE_SERVER", None)

        result = subprocess.run(
            [sys.executable, str(BACKEND_DIR / "core" / "server.py")],
            capture_output=True,
            text=True,
            cwd=BACKEND_DIR.parent,
            env=env,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("archived", result.stdout.lower())
        self.assertIn("backend/server.py", result.stdout)



if __name__ == "__main__":
    unittest.main(verbosity=2)
