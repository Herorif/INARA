"""Explicit local tool/model downloads. No global PATH or device changes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools/local-setup"
# This Windows host denied Gradle's AAR transform renames inside the workspace.
# A per-workspace user-temp cache passed the real build without security changes.
# Temporary storage can be cleared by the OS; explicit recording then restores it.
GRADLE_CACHE = Path(tempfile.gettempdir()) / (
    "inara-gradle-" + hashlib.sha256(str(ROOT).encode("utf-8")).hexdigest()[:12]
)


def fetch(url, limit=8_388_608):
    if not url.startswith("https://"):
        raise ValueError("HTTPS required")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 INARA-LocalSetup"}), timeout=120) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Metadata exceeded bound")
    return raw


def sha(path, algorithm="sha256"):
    value = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            value.update(block)
    return value.hexdigest()


def download(item):
    destination = TOOLS / "downloads" / item["name"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    algorithm = item.get("algorithm", "sha256")
    if destination.exists():
        if sha(destination, algorithm) != item["digest"]:
            raise ValueError("Existing download differs; preserve and inspect")
    else:
        partial = destination.with_suffix(destination.suffix + ".part")
        # Never silently replace a previous interrupted attempt.
        with urllib.request.urlopen(urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0 INARA-LocalSetup"}), timeout=120) as source, partial.open("xb") as target:
            total = 0
            while block := source.read(1_048_576):
                total += len(block)
                if total > 536_870_912:
                    raise ValueError("Download exceeded bound")
                target.write(block)
        if sha(partial, algorithm) != item["digest"]:
            raise ValueError("Official download checksum differs")
        partial.rename(destination)
    return {**item, "sha256": sha(destination), "path": str(destination)}


def extract(archive, output):
    marker = output / ".inara-extraction.json"
    digest = sha(archive)
    if output.exists():
        if marker.is_file() and json.loads(marker.read_text())["archive_sha256"] == digest:
            return
        raise ValueError("Existing extraction is incomplete; preserve it")
    with zipfile.ZipFile(archive) as stream:
        entries = stream.infolist()
        names, total = set(), 0
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            key = name.rstrip("/").casefold()
            total += entry.file_size
            if not name or "\\" in name or ":" in name or path.is_absolute() or ".." in path.parts or key in names or ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Unsafe archive entry")
            if total > 3_221_225_472 or len(entries) > 100000:
                raise ValueError("Archive exceeded extraction bound")
            names.add(key)
        output.mkdir(parents=True)
        stream.extractall(output)
    marker.write_text(json.dumps({"archive_sha256": digest}) + "\n")


def toolchain():
    jdk = json.loads(fetch("https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=windows"))[0]["binary"]["package"]
    gradle_url = "https://services.gradle.org/distributions/gradle-8.14.6-bin.zip"
    repository = ET.fromstring(fetch("https://dl.google.com/android/repository/repository2-1.xml"))
    package = next(p for p in repository if p.tag.endswith("remotePackage") and p.get("path") == "cmdline-tools;16.0")
    archive = next(a for a in package.find("archives") if a.findtext("host-os") == "windows").find("complete")
    items = [
        {"name": "jdk17-windows-x64.zip", "url": jdk["link"], "digest": jdk["checksum"]},
        {"name": "gradle-8.14.6-bin.zip", "url": gradle_url, "digest": fetch(gradle_url + ".sha256").decode().strip()},
        {"name": "android-commandline-16.0.zip", "url": "https://dl.google.com/android/repository/" + archive.findtext("url"), "algorithm": "sha1", "digest": archive.findtext("checksum")},
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        downloaded = list(pool.map(download, items))
    for name, item in zip(("jdk", "gradle-8.14.6", "android-commandline"), downloaded):
        extract(Path(item["path"]), TOOLS / name)
    java = next((TOOLS / "jdk").glob("*/bin/javac.exe")).parents[1]
    gradle = TOOLS / "gradle-8.14.6/gradle-8.14.6/bin"
    sdk = ROOT / ".tools/android-sdk"
    sdk.mkdir(parents=True, exist_ok=True)
    # Environment changes apply only when explicitly sourced in the current shell.
    env = [f"$env:JAVA_HOME = '{java}'", f"$env:ANDROID_HOME = '{sdk}'", f"$env:ANDROID_SDK_ROOT = '{sdk}'", f"$env:ANDROID_USER_HOME = '{ROOT / '.tools/android-user'}'",
           f"$env:GRADLE_USER_HOME = '{GRADLE_CACHE}'",
           f"$env:PATH = '{java / 'bin'};{gradle};{sdk / 'platform-tools'};' + $env:PATH"]
    network = []
    for kind, value in urllib.request.getproxies().items():
        if kind not in {"http", "https"}:
            continue
        proxy = urlsplit(value)
        if proxy.username or proxy.password or not proxy.hostname or not re.fullmatch(r"[a-zA-Z0-9.-]+", proxy.hostname):
            raise ValueError("Proxy credentials/custom hosts require separate local configuration")
        network += [f"systemProp.{kind}.proxyHost={proxy.hostname}", f"systemProp.{kind}.proxyPort={proxy.port or 80}"]
    cache = GRADLE_CACHE
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "gradle.properties").write_text("\n".join(network) + "\n")
    (ROOT / ".tools/local-env.ps1").write_text("\n".join(env) + "\n")
    (TOOLS / "downloads.json").write_text(json.dumps(downloaded, indent=2) + "\n")
    return {"downloaded": len(downloaded), "global_environment_changed": False, "device_accessed": False,
            "sdk_manager": str(TOOLS / "android-commandline/cmdline-tools/bin/sdkmanager.bat")}


def sdk():
    manager = TOOLS / "android-commandline/cmdline-tools/bin/sdkmanager.bat"
    command = [str(manager), "--sdk_root=" + str(ROOT / ".tools/android-sdk")]
    proxies = urllib.request.getproxies()
    proxy = urlsplit(proxies.get("https", proxies.get("http", "")))
    if proxy.hostname:
        if proxy.username or proxy.password or not re.fullmatch(r"[a-zA-Z0-9.-]+", proxy.hostname):
            raise ValueError("Unsupported proxy configuration")
        command += ["--proxy=http", "--proxy_host=" + proxy.hostname, "--proxy_port=" + str(proxy.port or 80)]
    logs = ROOT / ".runtime/local-setup"
    logs.mkdir(parents=True, exist_ok=True)
    for name, args, data in (("android-licenses.log", ["--licenses"], b"y\n" * 20), ("android-sdk.log", ["platforms;android-35", "build-tools;35.0.0", "platform-tools"], None)):
        with (logs / name).open("wb") as output:
            subprocess.run([*command, *args], input=data, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=1200)
    return {"sdk_components_installed": True, "device_accessed": False}


def voice_model():
    # Vosk publishes the model over HTTPS without a separate SHA-256 manifest.
    # This receipt records observed bytes, not independently signed provenance.
    url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
    path = TOOLS / "downloads/vosk-model-small-en-us-0.15.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        data = fetch(url, 67_108_864)
        with path.open("xb") as stream:
            stream.write(data)
    extract(path, ROOT / ".tools/local-voice")
    result = {"url": url, "sha256": sha(path), "upstream_signature_verified": False,
              "model": str(ROOT / ".tools/local-voice/vosk-model-small-en-us-0.15"), "microphone_opened": False}
    (TOOLS / "voice-model.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("toolchain", "voice-model", "sdk"))
    args = parser.parse_args()
    print(json.dumps({"toolchain": toolchain, "voice-model": voice_model, "sdk": sdk}[args.command](), indent=2))
