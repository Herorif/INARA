"""
Pytest configuration and shared fixtures for INARA tests.
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
    config._inara_previous_data = os.environ.get("INARA_DATA_DIR")
    config._inara_test_data = tempfile.TemporaryDirectory(prefix="inara-tests-")
    os.environ["INARA_DATA_DIR"] = config._inara_test_data.name


def pytest_unconfigure(config):
    if config._inara_previous_data is None:
        os.environ.pop("INARA_DATA_DIR", None)
    else:
        os.environ["INARA_DATA_DIR"] = config._inara_previous_data
    config._inara_test_data.cleanup()

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
