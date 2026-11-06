"""The published crystal J icons where they are used: the Android manifest and resources,
the Setup header (XAML and its wiring), the window and tray icons of the Electron hosts.

No Android SDK, Gradle or visible window: XML is parsed, resource references are resolved
against the res/ folder, and the Setup XAML is loaded by WPF without being shown.
"""

import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANDROID = "{http://schemas.android.com/apk/res/android}"
XAML = "{http://schemas.microsoft.com/winfx/2006/xaml/presentation}"
X = "{http://schemas.microsoft.com/winfx/2006/xaml}"
RES = ROOT / "android/app/src/main/res"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"
DENSITIES = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}
REFERENCE = re.compile(r"@(mipmap|drawable|color|xml|string|style)/([A-Za-z0-9_]+)")


def png_size(path):
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", data[16:24])


def resource_exists(kind, name):
    """A file res/<kind>[-qualifiers]/<name>.<ext>, or a values entry for colours/strings."""
    for folder in RES.iterdir():
        if folder.name == kind or folder.name.startswith(kind + "-"):
            if any(path.stem == name for path in folder.iterdir()):
                return True
    if kind in ("color", "string"):
        for path in RES.glob("values*/*.xml"):
            for element in ET.parse(path).getroot():
                if element.tag == kind and element.get("name") == name:
                    return True
    return False


def references(path):
    found = []
    for element in ET.parse(path).iter():
        for value in element.attrib.values():
            found += REFERENCE.findall(value)
    return found


# --- Android -------------------------------------------------------------------------------
def test_application_uses_the_launcher_mipmaps():
    application = ET.parse(MANIFEST).getroot().find("application")
    assert application.get(f"{ANDROID}icon") == "@mipmap/ic_launcher"
    assert application.get(f"{ANDROID}roundIcon") == "@mipmap/ic_launcher_round"


def test_every_manifest_and_resource_reference_exists():
    files = [MANIFEST, *RES.rglob("*.xml")]
    seen = set()
    for path in files:
        ET.parse(path)                                    # every XML file parses
        for kind, name in references(path):
            assert resource_exists(kind, name), f"{path.name}: @{kind}/{name}"
            seen.add(f"@{kind}/{name}")
    assert {"@mipmap/ic_launcher", "@mipmap/ic_launcher_round", "@mipmap/ic_launcher_foreground",
            "@mipmap/ic_launcher_monochrome", "@color/ic_launcher_background"} <= seen


def test_adaptive_icons_have_background_foreground_and_monochrome():
    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        root = ET.parse(RES / "mipmap-anydpi-v26" / name).getroot()
        assert root.tag == "adaptive-icon"
        assert [child.tag for child in root] == ["background", "foreground", "monochrome"]
    colour = ET.parse(RES / "values/ic_launcher_background.xml").getroot()
    assert [(c.tag, c.get("name"), c.text) for c in colour] == [
        ("color", "ic_launcher_background", "#05080C")]


def test_every_density_has_both_layers_at_its_size():
    for density, size in DENSITIES.items():
        for layer in ("foreground", "monochrome"):
            path = RES / f"mipmap-{density}" / f"ic_launcher_{layer}.png"
            assert png_size(path) == (size, size), path


def test_min_sdk_covers_the_anydpi_v26_launcher_icons():
    gradle = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
    assert int(re.search(r"minSdk\s*=\s*(\d+)", gradle).group(1)) >= 26
    assert int(re.search(r"compileSdk\s*=\s*(\d+)", gradle).group(1)) >= 33   # <monochrome>


# --- Setup header --------------------------------------------------------------------------
def setup_xaml():
    return ET.parse(ROOT / "native/setup/Setup.xaml").getroot()


def test_setup_header_is_the_emblem_image_with_the_wordmark():
    root = setup_xaml()
    images = [e for e in root.iter(f"{XAML}Image") if e.get(f"{X}Name") == "Emblem"]
    assert len(images) == 1
    assert images[0].attrib == {f"{X}Name": "Emblem", "Width": "64", "Height": "64",
                                "HorizontalAlignment": "Left", "Margin": "0,0,0,14",
                                "RenderOptions.BitmapScalingMode": "HighQuality"}
    assert not list(root.iter(f"{XAML}Ellipse")) and not list(root.iter(f"{XAML}Path"))
    texts = [e.get("Text") for e in root.iter(f"{XAML}TextBlock")]
    header = texts.index("J A R V I S")
    assert texts[header + 1] == "YOUR DESKTOP COMPANION"
    panel = next(p for p in root.iter(f"{XAML}StackPanel") if images[0] in list(p))
    assert list(panel).index(images[0]) == 0


def test_setup_script_sets_the_emblem_from_the_packaged_png():
    script = (ROOT / "scripts/setup-ui.ps1").read_text(encoding="utf-8")
    assert "native/setup/emblem-128.png" in script
    assert "BitmapCacheOption]::OnLoad" in script and "[UriKind]::Absolute" in script
    assert "GetFullPath" in script and "$script:ui.Emblem.Source = $image" in script
    # Wired after the named elements are found, before -BuildOnly returns.
    assert script.index("FindName($taskName)") < script.index("Set-SetupEmblem\n") \
        < script.index("if ($BuildOnly) {return}")


def load_setup(root):
    """Load the Setup UI with -BuildOnly (never shown) and report the emblem's image."""
    command = (
        f". '{root / 'scripts/setup-ui.ps1'}' -BuildOnly; "
        "$s = $script:ui.Emblem.Source; "
        "if ($s) { '{0} {1} {2}' -f $s.PixelWidth, $s.PixelHeight, $s.UriSource.IsAbsoluteUri }"
        " else { 'empty' }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", command],
        capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell.exe"),
                    reason="WPF needs Windows PowerShell")
def test_setup_xaml_loads_and_shows_the_128_px_emblem():
    assert load_setup(ROOT) == "128 128 True"


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell.exe"),
                    reason="WPF needs Windows PowerShell")
def test_setup_opens_with_an_empty_emblem_when_the_png_is_missing(tmp_path):
    for name in ("scripts/setup-ui.ps1", "native/setup/Setup.xaml"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, tmp_path / name)
    assert load_setup(tmp_path) == "empty"


# --- window and tray icons -----------------------------------------------------------------
def test_electron_hosts_use_the_multi_frame_ico_on_windows():
    native = (ROOT / "electron/native-main.cjs").read_text(encoding="utf-8")
    legacy = (ROOT / "electron/desktop.js").read_text(encoding="utf-8")
    choice = ("process.platform === 'win32' ? 'assets/icons/jarvis.ico' : "
              "'assets/icons/jarvis.png'")
    assert choice in native and legacy.count(choice) == 1
    assert "nativeImage.createFromPath(path.join(root, 'assets/icons/tray/jarvis-ready.ico'))" \
        in legacy


def ico_sizes(path):
    data = Path(path).read_bytes()
    assert struct.unpack_from("<HHH", data)[:2] == (0, 1)
    return [data[6 + 16 * i] or 256 for i in range(struct.unpack_from("<H", data, 4)[0])]


def test_window_and_tray_icons_have_their_frames():
    assert ico_sizes(ROOT / "assets/icons/jarvis.ico") == [16, 20, 24, 32, 40, 48, 64, 96, 128,
                                                          256]
    for state in ("ready", "talking", "calls", "attention", "paused"):
        assert ico_sizes(ROOT / f"assets/icons/tray/jarvis-{state}.ico") == [16, 20, 24, 32]
    assert png_size(ROOT / "assets/icons/jarvis.png") == (256, 256)
    assert png_size(ROOT / "native/setup/emblem-128.png") == (128, 128)


def test_ownership_lists_every_published_renderer_icon():
    entries = {e["path"]: e for e in json.loads(
        (ROOT / "docs/ASSET_OWNERSHIP.json").read_text(encoding="utf-8"))["entries"]}
    approvals = json.loads((ROOT / "art/icons/publish.json").read_text(encoding="utf-8"))
    for target in approvals["outputs"].values():
        if not target.startswith(("assets/", "public/", "src/")):
            assert target not in entries
            continue
        entry = entries[target]
        assert entry["sha256"] == hashlib.sha256((ROOT / target).read_bytes()).hexdigest()
        assert entry["origin"].startswith("owner-generated: scripts/build-icons.py (sha256 ")
        assert " from art/blender/jarvis-emblem.py (sha256 " in entry["origin"]
        assert entry["origin"].endswith(", Blender 5.2.3")
        assert (entry["owner"], entry["license_evidence"], entry["decision"]) == (None, [],
                                                                                   "pending")
    assert not [e for e in entries.values() if e["origin"] == "unverified-local-asset"
                and e["path"].startswith("assets/icons/")]
