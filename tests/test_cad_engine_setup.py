"""Static checks for the owner-run CAD engine setup script and its hashed lock."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-cad-kernel.lock"
SCRIPT = ROOT / "scripts" / "setup-cad-engine.ps1"
LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.+!-]+ --hash=sha256:[0-9a-f]{64}$")


def _entries() -> list[str]:
    lines = LOCK.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.strip() and not line.startswith("#")]


def test_lock_lines_are_pinned_and_hashed() -> None:
    entries = _entries()
    assert len(entries) >= 50
    for line in entries:
        assert LINE.match(line), line
    names = [line.split("==")[0].lower() for line in entries]
    assert len(names) == len(set(names))
    assert "pip" not in names and "setuptools" not in names


def test_lock_pins_build123d() -> None:
    assert any(line.startswith("build123d==0.13.0 ") for line in _entries())


def test_script_installs_only_hashed_wheels_after_consent() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for needle in ("--require-hashes", "--only-binary=:all:", "--use-feature=truststore", "[switch]$Yes", "Read-Host"):
        assert needle in text, needle
    assert "Box(20, 20, 10) - Cylinder(3, 10)" in text
    assert "3717.3" in text
    assert "-I -c $SmokeCode" in text


def test_script_never_changes_system_state() -> None:
    lowered = SCRIPT.read_text(encoding="utf-8").lower()
    for banned in (
        "set-itemproperty",
        "new-itemproperty",
        "setx",
        "[environment]::setenvironmentvariable",
        "hklm:",
        "hkcu:",
        "reg add",
        "$env:path =",
    ):
        assert banned not in lowered, banned
