"""Run a JARVIS Blender scene script headless into a review folder (developer tool).

Stdlib only. Finds Blender (JARVIS_BLENDER, else the default portable install), refuses
anything that is not Blender 5.2.x, and runs ``art/blender/<scene>.py`` with factory
settings, no audio and a minimal environment. Outputs land in
``.runtime/blender/review/`` with a ``<scene>.manifest.json`` (generator hash, Blender
version, output hashes); the log goes to ``.runtime/blender/logs/<scene>.log``.

Nothing reaches the repository unless ``--publish`` is given: that copies reviewed
outputs, unchanged and hash-checked, to the destinations approved in
``art/blender/publish.json``. Publishing does not rebuild and does not edit
docs/ASSET_OWNERSHIP.json; it prints the entries the owner should add (renderer assets only).

    python scripts/blender-build.py --list
    python scripts/blender-build.py jarvis-core [-- <scene args>]
    python scripts/blender-build.py jarvis-core --publish
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLENDER = Path.home() / "tools" / "blender-5.2.3-windows-x64" / "blender.exe"
SUPPORTED = (5, 2)
SCENE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
OUTPUT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
# native/setup/ holds the Setup window's packaged art. It is not a renderer asset, so it gets
# no docs/ASSET_OWNERSHIP.json entry (renderer-provenance.py refuses those).
PUBLISH_PREFIXES = ("public/", "assets/", "src/assets/", "native/setup/")
RENDERER_PREFIXES = ("public/", "assets/", "src/")
HEADLESS = ("-b", "--factory-startup", "-noaudio", "--python-exit-code", "1")
# Variables Blender, the GPU driver and Windows need; everything else (keys, PYTHONPATH,
# user tool paths) is dropped. Blender's own Python ignores PYTHON* variables anyway.
KEEP = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
    "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS", "OS",
)


class BuildError(Exception):
    pass


def paths(root):
    runtime = root / ".runtime" / "blender"
    return {
        "scenes": root / "art" / "blender",
        "logs": runtime / "logs",
        "build": runtime / "build",
        "review": runtime / "review",
        "home": runtime / "home",
    }


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return value.hexdigest()


def find_blender(environ):
    """JARVIS_BLENDER wins when set (and must exist); otherwise the default install."""
    configured = environ.get("JARVIS_BLENDER", "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_file():
            raise BuildError(f"JARVIS_BLENDER does not point to a file: {candidate}")
        return candidate
    if DEFAULT_BLENDER.is_file():
        return DEFAULT_BLENDER
    raise BuildError(
        f"Blender not found at {DEFAULT_BLENDER}; set JARVIS_BLENDER to blender.exe (5.2.x)"
    )


def clean_environment(environ, home):
    env = {key: environ[key] for key in KEEP if environ.get(key)}
    if os.name == "nt":
        system = environ.get("SYSTEMROOT", r"C:\Windows")
        env["PATH"] = os.pathsep.join([system + r"\System32", system])
    else:
        env["PATH"] = "/usr/bin:/bin"
    # Isolated user config/scripts/extensions: no add-ons or startup files leak in.
    env["BLENDER_USER_RESOURCES"] = str(home)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def parse_version(text):
    match = re.search(r"^Blender (\d+)\.(\d+)\.(\d+)", text, re.M)
    if not match:
        raise BuildError("Could not read the Blender version")
    return tuple(int(part) for part in match.groups())


def check_version(version):
    if tuple(version[:2]) != SUPPORTED:
        found = ".".join(map(str, version))
        raise BuildError(f"Blender {found} is not supported; this pipeline requires 5.2.x")
    return ".".join(map(str, version))


def blender_version(executable, env, run=subprocess.run):
    result = run(
        [str(executable), "-b", "--factory-startup", "-noaudio", "--version"],
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode != 0:
        raise BuildError(f"Blender --version failed with exit code {result.returncode}")
    return check_version(parse_version(result.stdout))


def scene_script(root, name):
    if not isinstance(name, str) or not SCENE_NAME.fullmatch(name):
        raise BuildError(f"Invalid scene name {name!r}: use lower-case letters, digits and '-'")
    script = paths(root)["scenes"] / f"{name}.py"
    if not script.is_file():
        raise BuildError(f"No scene script art/blender/{name}.py")
    return script


def list_scenes(root):
    folder = paths(root)["scenes"]
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.py") if SCENE_NAME.fullmatch(p.stem))


def command(executable, script, out, scene_args):
    return [str(executable), *HEADLESS, "--python", str(script), "--", "--out", str(out),
            *scene_args]


def check_scene_args(scene_args):
    for value in scene_args:
        if not isinstance(value, str) or any(ch in value for ch in "\r\n\0"):
            raise BuildError("Scene arguments must be single-line strings")
        if value == "--out":
            raise BuildError("--out is set by blender-build.py, not by the caller")
    return list(scene_args)


def collect_outputs(folder):
    outputs = {}
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or not path.is_file() or not OUTPUT_NAME.fullmatch(path.name):
            raise BuildError(f"Unexpected scene output {path.name!r} (flat regular files only)")
        if path.name.endswith(".manifest.json"):
            raise BuildError(f"Scene output {path.name!r} uses a reserved name")
        outputs[path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    if not outputs:
        raise BuildError("The scene produced no outputs")
    return outputs


def build(root, name, scene_args, environ, run=subprocess.run, timeout=1800):
    where = paths(root)
    script = scene_script(root, name)
    scene_args = check_scene_args(scene_args)
    executable = find_blender(environ)
    for key in ("logs", "review", "home"):
        where[key].mkdir(parents=True, exist_ok=True)
    env = clean_environment(environ, where["home"])
    version = blender_version(executable, env, run=run)
    print(f"Blender {version} at {executable}")
    staging = where["build"] / name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    log = where["logs"] / f"{name}.log"
    argv = command(executable, script, staging, scene_args)
    with log.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("$ " + " ".join(argv) + "\n")
        stream.flush()
        result = run(argv, env=env, cwd=str(staging), stdout=stream, stderr=subprocess.STDOUT,
                     text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise BuildError(f"Scene {name} failed (exit {result.returncode}); see {log}")
    outputs = collect_outputs(staging)
    manifest_path = where["review"] / f"{name}.manifest.json"
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8")).get("outputs", {})
        except (OSError, ValueError, AttributeError):
            previous = {}
        for old in previous:
            if OUTPUT_NAME.fullmatch(old) and old not in outputs:
                (where["review"] / old).unlink(missing_ok=True)
    for output in outputs:
        shutil.copyfile(staging / output, where["review"] / output)
    manifest = {
        "format": 1,
        "scene": name,
        "generator": f"art/blender/{name}.py",
        "generator_sha256": sha256(script),
        "blender_version": version,
        "scene_args": scene_args,
        "outputs": outputs,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(f"{len(outputs)} output(s) for review in {where['review']}")
    print(f"log: {log}")
    return manifest


def publish_targets(root, name):
    approvals = paths(root)["scenes"] / "publish.json"
    try:
        value = json.loads(approvals.read_text(encoding="utf-8"))
    except FileNotFoundError:
        value = {"format": 1, "scenes": {}}
    if value.get("format") != 1 or not isinstance(value.get("scenes"), dict):
        raise BuildError("art/blender/publish.json is not a format 1 approvals file")
    targets = value["scenes"].get(name) or {}
    if not isinstance(targets, dict) or not targets:
        raise BuildError(f"No approved outputs for {name} in art/blender/publish.json")
    for output, target in targets.items():
        if (
            not isinstance(target, str)
            or not target.startswith(PUBLISH_PREFIXES)
            or "\\" in target
            or any(part in ("", ".", "..") for part in target.split("/"))
            or not OUTPUT_NAME.fullmatch(output)
        ):
            raise BuildError(f"Unsupported publish destination for {output!r}: {target!r}")
    return targets


def publish(root, name):
    where = paths(root)
    script = scene_script(root, name)
    manifest_path = where["review"] / f"{name}.manifest.json"
    if not manifest_path.is_file():
        raise BuildError(f"Nothing reviewed for {name}: build it first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("scene") != name or manifest.get("format") != 1:
        raise BuildError("Review manifest does not belong to this scene")
    check_version(parse_version("Blender " + str(manifest.get("blender_version"))))
    if manifest.get("generator_sha256") != sha256(script):
        raise BuildError("The scene script changed since review; rebuild and review again")
    targets = publish_targets(root, name)
    entries = []
    for output, target in targets.items():
        record = manifest["outputs"].get(output)
        source = where["review"] / output
        if record is None or not source.is_file() or sha256(source) != record["sha256"]:
            raise BuildError(f"Reviewed output {output} is missing or changed since review")
        destination = root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if sha256(destination) != record["sha256"]:
            raise BuildError(f"Copy of {output} does not match its reviewed hash")
        print(f"published {output} -> {target}")
        if not target.startswith(RENDERER_PREFIXES):
            continue
        entries.append({
            "path": target,
            "sha256": record["sha256"],
            "origin": (f"owner-generated: {manifest['generator']} "
                       f"(sha256 {manifest['generator_sha256']}), "
                       f"Blender {manifest['blender_version']}"),
            "owner": None,
            "license_evidence": [],
            "decision": "pending",
        })
    print("Add to docs/ASSET_OWNERSHIP.json once the owner confirms:")
    print(json.dumps(entries, indent=2))
    return entries


def main(argv=None, environ=None, root=ROOT, run=subprocess.run):
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    scene_args = []
    if "--" in argv:
        index = argv.index("--")
        argv, scene_args = argv[:index], argv[index + 1:]
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scene", nargs="?", help="scene name: art/blender/<scene>.py")
    parser.add_argument("--list", action="store_true", help="list the available scenes")
    parser.add_argument("--publish", action="store_true",
                        help="copy reviewed outputs to their approved repo locations")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds (default 1800)")
    args = parser.parse_args(argv)
    try:
        if args.list:
            for scene in list_scenes(root):
                print(scene)
            return 0
        if not args.scene:
            parser.error("a scene name is required")
        if args.publish:
            if scene_args:
                raise BuildError("--publish copies reviewed outputs; it takes no scene arguments")
            publish(root, args.scene)
        else:
            if not 1 <= args.timeout <= 86400:
                raise BuildError("--timeout must be between 1 and 86400 seconds")
            build(root, args.scene, scene_args, environ, run=run, timeout=args.timeout)
    except (BuildError, subprocess.TimeoutExpired) as error:
        print(f"blender-build: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
