"""
Pytest configuration and shared fixtures for JARVIS tests.
"""
import pytest
import sys
import os
import json
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def pytest_configure(config):
    """Isolate storage before collection: smoke tests import the server at module scope."""
    import tempfile
    config._jarvis_previous_data = os.environ.get("JARVIS_DATA_DIR")
    config._jarvis_test_data = tempfile.TemporaryDirectory(prefix="jarvis-tests-")
    os.environ["JARVIS_DATA_DIR"] = config._jarvis_test_data.name
    config._jarvis_previous_isolation = {key: os.environ.get(key) for key in
                                       ("JARVIS_PROJECT_ROOT", "JARVIS_LEGACY_DATA_DIR", "JARVIS_SETTINGS_FILE",
                                        "JARVIS_WAKE_WORD_DIR")}
    os.environ["JARVIS_PROJECT_ROOT"] = config._jarvis_test_data.name
    os.environ["JARVIS_LEGACY_DATA_DIR"] = config._jarvis_test_data.name
    os.environ["JARVIS_SETTINGS_FILE"] = str(Path(config._jarvis_test_data.name) / "settings.json")
    # An empty model folder: no test ever sees the real wake-word models (the opt-in
    # live_wake tests name the real folder explicitly).
    config._jarvis_wake_models = tempfile.TemporaryDirectory(prefix="jarvis-wake-tests-")
    os.environ["JARVIS_WAKE_WORD_DIR"] = config._jarvis_wake_models.name


# Opt-in markers (registered in pytest.ini): marker -> environment switch.
OPT_IN_MARKERS = {
    "live_api": "JARVIS_LIVE_API_TESTS",
    "live_hardware": "JARVIS_LIVE_HARDWARE_TESTS",
    "live_blender": "JARVIS_LIVE_BLENDER_TESTS",
    "live_wake": "JARVIS_LIVE_WAKE_TESTS",
}


def pytest_collection_modifyitems(config, items):
    """Skip paid-API and real-device tests unless their switch is exactly "1"."""
    for marker, variable in OPT_IN_MARKERS.items():
        from services import env  # INARA_* switches still work for one release

        if env.getenv(variable) == "1":
            continue
        skip = pytest.mark.skip(reason=f"{marker} test: set {variable}=1 to run it")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)


def pytest_unconfigure(config):
    for key, value in config._jarvis_previous_isolation.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    if config._jarvis_previous_data is None:
        os.environ.pop("JARVIS_DATA_DIR", None)
    else:
        os.environ["JARVIS_DATA_DIR"] = config._jarvis_previous_data
    config._jarvis_test_data.cleanup()
    config._jarvis_wake_models.cleanup()

# Settings file path
SETTINGS_FILE = BACKEND_DIR / "settings.json"


@pytest.fixture(scope="session")
def settings():
    """Load settings.json for device configurations."""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}


@pytest.fixture(scope="session")
def kasa_devices(settings):
    """Get Kasa devices from settings."""
    return settings.get("kasa_devices", [])


@pytest.fixture(scope="session")
def printers(settings):
    """Get printers from settings."""
    return settings.get("printers", [])


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for file operations."""
    return tmp_path


@pytest.fixture
def sample_stl_content():
    """Sample minimal STL file content for testing."""
    return """solid test
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0.5 1 0
    endloop
  endfacet
endsolid test"""

@pytest.fixture
def application_factory(tmp_path):
    """Fresh composition root; never replace live server module globals."""
    from application import create_application
    from services.storage import Database
    from unittest.mock import AsyncMock

    applications = []

    def create(**overrides):
        root = tmp_path / str(len(applications))
        root.mkdir()
        # The morning briefing (P2) is off here: its trigger reads the real clock, so a
        # test run between 06:00 and 11:00 would otherwise play it. Its own tests turn it on.
        # World view is off too: on a PC with God's Eye View installed, startup would list
        # the real gev MCP server's tools. Its own tests point world.* at fakes.
        values = dict(settings={"face_auth_enabled": False, "tool_permissions": {},
                                "kasa_devices": [], "briefing": {"enabled": False},
                                "world": {"enabled": False}},
                      project_root=root, legacy_data_dir=root,
                      database=Database(root / "private"))
        values.update(overrides)
        runtime = create_application(**values)
        runtime.sio.emit = AsyncMock()
        from types import SimpleNamespace
        runtime.connection.check_setup = lambda: None
        runtime.connection.worker_factory = lambda: SimpleNamespace(run=AsyncMock(), close=AsyncMock())
        applications.append(runtime)
        return runtime

    return create
