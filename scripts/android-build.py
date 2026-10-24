"""Offline Android build evidence. No downloads, device access or private profiles."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PINS = {"java": "17", "gradle": "8.14.6", "platform": "35", "build_tools": "35.0.0"}
CONFIGURATIONS = {
    "debugCompileClasspath",
    "debugRuntimeClasspath",
    "debugUnitTestCompileClasspath",
    "debugUnitTestRuntimeClasspath",
}


def bounded(path, maximum=4_194_304):
    if path.is_symlink() or path.resolve() != path.absolute() or not path.is_file():
        raise ValueError("Missing or linked build input/output")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Build evidence exceeded its bound")
    return raw


def digest(path):
    if path.is_symlink() or path.resolve() != path.absolute() or not path.is_file():
        raise ValueError("Missing or linked build input/output")
    total = 0
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            total += len(chunk)
            if total > 134_217_728:
                raise ValueError("Build input/output exceeded its bound")
            value.update(chunk)
    return value.hexdigest()


def inputs(root):
    android = root / "android"
    paths = sorted(
        path
        for path in android.rglob("*")
        if path.is_file()
        and not {"build", ".gradle", ".idea"}.intersection(path.relative_to(android).parts)
        and (
            path.suffix in {".kt", ".xml", ".kts"}
            or path.name in {"gradle.properties", "build.ps1"}
        )
    )
    if not paths or len(paths) > 512:
        raise ValueError("Unexpected Android source inventory")
    # Dependency metadata is recorded separately: bootstrapping creates that file.
    paths = [path for path in paths if path.name != "verification-metadata.xml"]
    if (root / "scripts/android-build.py").is_file():
        paths.append(root / "scripts/android-build.py")
    return {path.relative_to(root).as_posix(): digest(path) for path in paths}


def dependency_state(root):
    android = root / "android"
    lock = bounded(android / "app/gradle.lockfile").decode("utf-8")
    locked = set()
    for line in lock.splitlines():
        if line and not line.startswith("#"):
            coordinate, configurations = line.rsplit("=", 1)
            if not coordinate or any(value in coordinate for value in ("+", "SNAPSHOT", "latest.")):
                raise ValueError("Dependency locks contain an unsupported version")
            locked.update(configurations.split(","))
    if not CONFIGURATIONS.issubset(locked):
        raise ValueError("Debug and unit-test classpaths are not fully locked")
    path = android / "gradle/verification-metadata.xml"
    raw = bounded(path)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Unexpected dependency XML declaration")
    document = ET.fromstring(raw)
    ns = {"v": "https://schema.gradle.org/dependency-verification"}
    if document.tag != "{" + ns["v"] + "}verification-metadata":
        raise ValueError("Unexpected verification metadata")
    if document.findtext("v:configuration/v:verify-metadata", namespaces=ns) != "true":
        raise ValueError("Dependency metadata verification must be enabled")
    if document.findall(".//v:trusted-artifacts/v:trust", ns):
        raise ValueError("Broad dependency trust exclusions are not accepted")
    artifacts = document.findall("v:components/v:component/v:artifact", ns)
    if not artifacts or len(artifacts) > 20000:
        raise ValueError("Dependency artifact inventory is empty or excessive")
    for artifact in artifacts:
        hashes = artifact.findall("v:sha256", ns)
        if not hashes or any(
            not re.fullmatch("[a-fA-F0-9]{64}", item.get("value", "")) for item in hashes
        ):
            raise ValueError("Every resolved artifact needs a SHA-256")
    return {
        "lock_sha256": digest(android / "app/gradle.lockfile"),
        "verification_sha256": hashlib.sha256(raw).hexdigest(),
        "artifacts": len(artifacts),
    }


def preflight(root=ROOT):
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    tools = {name: shutil.which(name) is not None for name in ("java", "javac", "gradle")}
    components = {"platform": False, "build_tools": False, "apksigner": False}
    if sdk:
        sdk = Path(sdk)
        components = {
            "platform": (sdk / "platforms/android-35/android.jar").is_file(),
            "build_tools": (sdk / "build-tools/35.0.0").is_dir(),
            "apksigner": any(
                (sdk / "build-tools/35.0.0" / name).is_file()
                for name in ("apksigner", "apksigner.bat")
            ),
        }
    try:
        dependency_state(root)
        dependencies = True
    except (OSError, ValueError, ET.ParseError):
        dependencies = False
    return {
        "format": 1,
        "pins": PINS,
        "tools_present": tools,
        "sdk_present": components,
        "dependencies_recorded": dependencies,
        "tool_versions_verified": False,
        "can_attempt_offline_build": all(tools.values())
        and all(components.values())
        and dependencies,
        "apk_compiled": False,
        "device_accessed": False,
        "network_accessed": False,
        "note": "Presence only. Build runner verifies exact tool versions; checksums need independent review after first resolution.",
    }


def run_directory(root, identifier):
    identifier = str(uuid.UUID(identifier))
    base = root / ".runtime/android-build"
    path = base / identifier
    if path.resolve() != path.absolute():
        raise ValueError("Linked evidence directory is not accepted")
    return path


def begin(root=ROOT, record=False):
    check = preflight(root)
    if not all(check["tools_present"].values()) or not all(check["sdk_present"].values()):
        raise ValueError(
            "Pinned JDK/Gradle/SDK tools are missing. Run preflight; nothing was installed."
        )
    if not record:
        dependency_state(root)
    identifier = str(uuid.uuid4())
    directory = run_directory(root, identifier)
    directory.mkdir(parents=True)
    value = {
        "format": 1,
        "id": identifier,
        "started_ns": time.time_ns(),
        "record_dependencies": record,
        "inputs": inputs(root),
        "dependencies": None if record else dependency_state(root),
    }
    (directory / "begin.json").write_text(json.dumps(value), encoding="utf-8")
    return identifier


def junit(root, started):
    folder = root / "android/app/build/test-results/testDebugUnitTest"
    reports = sorted(folder.glob("TEST-*.xml"))
    if not reports or len(reports) > 100:
        raise ValueError("Fresh JVM test reports are required")
    tests = 0
    hashes = {}
    for path in reports:
        if path.stat().st_mtime_ns < started:
            raise ValueError("Stale JVM test report")
        raw = bounded(path)
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("Unexpected test XML declaration")
        suite = ET.fromstring(raw)
        cases = suite.findall("testcase")
        if (
            suite.tag != "testsuite"
            or int(suite.get("failures", "0"))
            or int(suite.get("errors", "0"))
            or int(suite.get("skipped", "0"))
        ):
            raise ValueError("JVM tests failed")
        if not cases or any(
            case.find("failure") is not None
            or case.find("error") is not None
            or case.find("skipped") is not None
            for case in cases
        ):
            raise ValueError("JVM test cases must execute and pass")
        if int(suite.get("tests", "0")) != len(cases):
            raise ValueError("Inconsistent JVM test counts")
        tests += len(cases)
        hashes[path.name] = hashlib.sha256(raw).hexdigest()
    if not any("MobileProtocolTest" in name for name in hashes):
        raise ValueError("The protocol-vector JVM suite must run")
    return {"tests": tests, "reports": hashes}


def apk(path):
    # Structural audit complements apksigner; it is not signature verification.
    if not 0 < path.stat().st_size <= 134_217_728:
        raise ValueError("Unexpected debug APK size")
    digest(path)  # Validate containment/link policy before opening the archive.
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) > 20000 or len(set(names)) != len(names):
            raise ValueError("Duplicate or excessive APK entries")
        if any(
            name.startswith(("/", "\\")) or "\\" in name or ".." in name.split("/")
            for name in names
        ):
            raise ValueError("Unsafe APK entry")
        if sum(entry.file_size for entry in entries) > 536_870_912:
            raise ValueError("APK expanded size exceeded its bound")
        if not {"AndroidManifest.xml", "classes.dex", "resources.arsc"}.issubset(names):
            raise ValueError("APK lacks compiled Android components")
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def complete(root, identifier, build_exit, signature_exit):
    directory = run_directory(root, identifier)
    receipt = json.loads(bounded(directory / "begin.json"))
    if (
        not isinstance(receipt, dict)
        or receipt.get("format") != 1
        or receipt.get("id") != str(uuid.UUID(identifier))
        or type(receipt.get("started_ns")) is not int
        or receipt["started_ns"] <= 0
        or type(receipt.get("record_dependencies")) is not bool
        or not isinstance(receipt.get("inputs"), dict)
    ):
        raise ValueError("Invalid build-start receipt")
    result = {
        "format": 1,
        "id": identifier,
        "accepted_debug_build": False,
        "release_signed": False,
        "device_verified": False,
        "record_dependencies": receipt["record_dependencies"],
    }
    try:
        if build_exit != 0 or signature_exit != 0:
            raise ValueError("Gradle tasks or APK signature verification failed")
        if receipt["inputs"] != inputs(root):
            raise ValueError("Android inputs changed during the build")
        dependencies = dependency_state(root)
        if not receipt["record_dependencies"] and dependencies != receipt["dependencies"]:
            raise ValueError("Locked dependency metadata changed during strict build")
        toolchain = json.loads(bounded(directory / "toolchain.json", 4096))
        if toolchain != {key: PINS[key] for key in ("java", "gradle")}:
            raise ValueError("The exact pinned toolchain was not verified")
        target = root / "android/app/build/outputs/apk/debug/app-debug.apk"
        if target.stat().st_mtime_ns < receipt["started_ns"]:
            raise ValueError("Stale APK output")
        signature = bounded(directory / "apksigner.txt", 262144).decode(
            "utf-8-sig", errors="replace"
        )
        certificates = re.findall(r"certificate SHA-256 digest:\s*([a-fA-F0-9]{64})", signature)
        if not certificates:
            raise ValueError("APK signer certificate evidence is missing")
        result.update(
            apk=apk(target),
            junit=junit(root, receipt["started_ns"]),
            dependencies=dependencies,
            signer_sha256=sorted(set(certificates)),
            signature_verified=True,
            accepted_debug_build=not receipt["record_dependencies"],
            dependency_review_required=receipt["record_dependencies"],
        )
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
        result["error"] = (
            "Build acceptance failed. Inspect the local Gradle/signature output and input/dependency/test evidence."
        )
    (directory / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    start = commands.add_parser("begin")
    start.add_argument("--record-dependencies", action="store_true")
    finish = commands.add_parser("complete")
    finish.add_argument("--run", required=True)
    finish.add_argument("--build-exit", required=True, type=int)
    finish.add_argument("--signature-exit", required=True, type=int)
    args = parser.parse_args()
    try:
        if args.command == "preflight":
            print(json.dumps(preflight(), indent=2))
        elif args.command == "begin":
            print(begin(record=args.record_dependencies))
        else:
            result = complete(ROOT, args.run, args.build_exit, args.signature_exit)
            print(json.dumps(result, indent=2))
            return 0 if result.get("signature_verified") else 2
    except (OSError, ValueError, ET.ParseError):
        print(
            "Android build evidence is unavailable or incomplete. Run preflight; no tool or dependency was installed."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
