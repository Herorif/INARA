"""Compatibility paths fail closed without importing optional browser/provider SDKs."""
import importlib
import pytest


@pytest.mark.parametrize("module", ["web_agent", "agents.web_agent"])
def test_retired_autonomous_browser_cannot_be_constructed(module):
    value = importlib.import_module(module)
    with pytest.raises(RuntimeError, match="retired"):
        value.WebAgent()
