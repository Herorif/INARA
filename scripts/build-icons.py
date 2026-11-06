"""Build the JARVIS icon set for review from the reviewed emblem renders (developer tool).

Stdlib only. Reads the jarvis-emblem renders from ``.runtime/blender/review/`` (checked
against ``jarvis-emblem.manifest.json`` and the current scene script), draws the small
frames (16, 20, 24 and the 32 px tray frames) on the pixel grid, and writes the icon
files into a freshly emptied ``.runtime/icons/review/`` with a ``manifest.json`` (each
output's path, byte size, SHA-256 and pixel sizes). The same inputs give the same bytes.

Nothing reaches the repository unless ``--publish`` is given: that copies the reviewed
bytes, without rebuilding, to the destinations approved in ``art/icons/publish.json`` and
prints the ``docs/ASSET_OWNERSHIP.json`` entries for the renderer assets among them.

    python scripts/build-icons.py
    python scripts/build-icons.py --publish
"""

import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = Path(__file__).resolve()
SCENE = "jarvis-emblem"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# --- design -----------------------------------------------------------------------------
DISC = "#0A1017"
FULL_RENDERS = (48, 64, 96, 128, 256)
SIMPLE_RENDERS = (32, 40)
PIXEL_SIZES = (16, 20, 24)
TRAY_SIZES = (16, 20, 24, 32)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
ANDROID_DENSITIES = (("mdpi", 108), ("hdpi", 162), ("xhdpi", 216), ("xxhdpi", 324),
                     ("xxxhdpi", 432))
ANDROID_BACKGROUND = "#05080C"
# In-app brand mark (src/assets/icons): 24 is the ready pixel frame, 32 the simplified
# render, 48 and up the full renders (24/32/48 at 1x, with 48/64/96 as their 2x).
UI_MARKS = (24, 32, 48, 64, 96)
# Publishing: approved destinations must sit under one of these repository folders.
PUBLISH_PREFIXES = ("assets/", "src/assets/", "android/app/src/main/res/", "native/setup/")
# Renderer assets (docs/ASSET_OWNERSHIP.json covers these only).
RENDERER_PREFIXES = ("assets/", "public/", "src/")

# J pixel frames: origin (left column, top row), then one string per row.
# "L" is the light (left) stem column(s), "M" the rest of the J, "." empty.
J_PIXELS = {
    16: ((5, 3), (
        "....LM",
        "....LM",
        "....LM",
        "....LM",
        "....LM",
        "....LM",
        "M...LM",
        "MM..LM",
        ".MMMM.",
    )),
    20: ((6, 4), (
        "......LM",
        "......LM",
        "......LM",
        "......LM",
        "......LM",
        "......LM",
        "......LM",
        "MM....LM",
        "MMM...LM",
        "MMMMMMMM",
        ".MMMMMM.",
    )),
    24: ((7, 5), (
        ".......LMM",
        ".......LMM",
        ".......LMM",
        ".......LMM",
        ".......LMM",
        ".......LMM",
        ".......LMM",
        ".......LMM",
        "MMM....LMM",
        "MMMM...LMM",
        "MMMMMMMMMM",
        "MMMMMMMMMM",
        ".MMMMMMMM.",
    )),
    32: ((10, 7), (
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "........LLMM",
        "MMMM....LLMM",
        "MMMM....LLMM",
        "MMMMM...LLMM",
        "MMMMMMMMMMMM",
        "MMMMMMMMMMMM",
        ".MMMMMMMMMM.",
        "..MMMMMMMM..",
    )),
}

# Tray states: ring colour, ring radius and width (as fractions of the size, from the
# 16 px design), J light and rest colours, and the badge colour (None: no badge).
STATES = {
    "ready": {"ring": "#2A8A96", "ring_r": 7.3 / 16, "ring_w": 1.0 / 16,
              "light": "#B0EFF5", "rest": "#70E0ED", "badge": None},
    "talking": {"ring": "#70E0ED", "ring_r": 7.2 / 16, "ring_w": 1.4 / 16,
                "light": "#EFFCFD", "rest": "#B0EFF5", "badge": None},
    "paused": {"ring": "#3A4A5C", "ring_r": 7.3 / 16, "ring_w": 1.0 / 16,
               "light": "#9FB0BF", "rest": "#74849A", "badge": None},
    "calls": {"ring": "#2A8A96", "ring_r": 7.3 / 16, "ring_w": 1.0 / 16,
              "light": "#B0EFF5", "rest": "#70E0ED", "badge": "#6DE2B5"},
    "attention": {"ring": "#2A8A96", "ring_r": 7.3 / 16, "ring_w": 1.0 / 16,
                  "light": "#B0EFF5", "rest": "#70E0ED", "badge": "#FFC670"},
}

# Badge: centre (x, y) per size; radius 2.6/16 and a 1/16 outline (#0A1017) of the size.
# 16 px is the design; the larger centres are the scaled ones nudged by at most half a
# pixel so the dot clears the J's corner, which sits closer at the larger pixel designs.
BADGE_CENTRE = {16: (13.0, 13.0), 20: (16.5, 16.5), 24: (20.0, 20.0), 32: (26.5, 26.5)}
BADGE_R, BADGE_OUTLINE = 2.6 / 16, 1.0 / 16

SUBSAMPLES = 16     # per axis: 256 coverage samples per pixel


class IconError(Exception):
    pass


def paths(root):
    return {
        "renders": root / ".runtime" / "blender" / "review",
        "scene": root / "art" / "blender" / f"{SCENE}.py",
        "out": root / ".runtime" / "icons" / "review",
    }


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def rgb(code):
    code = code.lstrip("#")
    return tuple(int(code[i:i + 2], 16) for i in (0, 2, 4))


# --- PNG --------------------------------------------------------------------------------
def png_chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def encode_png(width, height, rgba):
    """8-bit RGBA, no interlace, filter 0 on every row, zlib level 9: deterministic."""
    if len(rgba) != width * height * 4:
        raise IconError("RGBA buffer does not match the image size")
    stride = width * 4
    raw = b"".join(b"\x00" + bytes(rgba[y * stride:(y + 1) * stride]) for y in range(height))
    return (PNG_SIGNATURE
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(raw, 9))
            + png_chunk(b"IEND", b""))


def png_info(data):
    """Check the signature and chunk CRCs; return (width, height, bit depth, colour type)."""
    if data[:8] != PNG_SIGNATURE:
        raise IconError("not a PNG")
    offset, header, seen_end = 8, None, False
    while offset < len(data):
        if offset + 12 > len(data):
            raise IconError("truncated PNG chunk")
        length, kind = struct.unpack_from(">I4s", data, offset)
        body = data[offset + 4:offset + 8 + length]
        if len(body) != 4 + length:
            raise IconError("truncated PNG chunk")
        (crc,) = struct.unpack_from(">I", data, offset + 8 + length)
        if zlib.crc32(body) & 0xFFFFFFFF != crc:
            raise IconError(f"bad CRC in PNG chunk {kind!r}")
        if kind == b"IHDR":
            header = struct.unpack(">IIBB", body[4:14])
        offset += 12 + length
        if kind == b"IEND":
            seen_end = True
            break
    if header is None or not seen_end or offset != len(data):
        raise IconError("PNG lacks IHDR or IEND, or has trailing data")
    return header


# --- ICO --------------------------------------------------------------------------------
def encode_ico(frames):
    """`frames`: [(size, png bytes)], every frame PNG-compressed, in the given order."""
    count = len(frames)
    offset = 6 + 16 * count
    header = struct.pack("<HHH", 0, 1, count)
    entries, payloads = [], []
    for size, data in frames:
        width, height, depth, colour = png_info(data)
        if (width, height) != (size, size) or (depth, colour) != (8, 6):
            raise IconError(f"ICO frame {size}: PNG is {width}x{height}, depth {depth}, "
                            f"colour type {colour}; need {size}x{size} 8-bit RGBA")
        byte = 0 if size == 256 else size
        entries.append(struct.pack("<BBBBHHII", byte, byte, 0, 0, 1, 32, len(data), offset))
        payloads.append(data)
        offset += len(data)
    return header + b"".join(entries) + b"".join(payloads)


# --- pixel frames -----------------------------------------------------------------------
@lru_cache(maxsize=None)
def coverage(size, cx, cy, r_in, r_out):
    """Supersampled area of the annulus r_in..r_out (r_in 0: a disc) in each pixel."""
    n = SUBSAMPLES
    offsets = [(i + 0.5) / n for i in range(n)]
    lo2, hi2 = r_in * r_in, r_out * r_out
    out = [0.0] * (size * size)
    for y in range(size):
        if y + 1 < cy - r_out or y > cy + r_out:
            continue
        for x in range(size):
            if x + 1 < cx - r_out or x > cx + r_out:
                continue
            hits = 0
            for oy in offsets:
                dy2 = (y + oy - cy) ** 2
                for ox in offsets:
                    d2 = (x + ox - cx) ** 2 + dy2
                    if lo2 <= d2 <= hi2:
                        hits += 1
            out[y * size + x] = hits / (n * n)
    return tuple(out)


class Canvas:
    """Straight-alpha RGBA in display (sRGB) space, composited 'over' like a browser."""

    def __init__(self, size):
        self.size = size
        self.px = [(0.0, 0.0, 0.0, 0.0)] * (size * size)

    def over(self, index, colour, alpha):
        if alpha <= 0.0:
            return
        r, g, b, a = self.px[index]
        out_a = alpha + a * (1.0 - alpha)
        mix = [(c * alpha + d * a * (1.0 - alpha)) / out_a
               for c, d in zip(colour, (r, g, b), strict=True)]
        self.px[index] = (*mix, out_a)

    def shape(self, code, cover):
        colour = tuple(c / 255.0 for c in rgb(code))
        for index, alpha in enumerate(cover):
            self.over(index, colour, alpha)

    def pixel(self, x, y, code):
        self.px[y * self.size + x] = (*[c / 255.0 for c in rgb(code)], 1.0)

    def rgba(self):
        out = bytearray()
        for pixel in self.px:
            out += bytes(min(255, max(0, round(c * 255.0))) for c in pixel)
        return bytes(out)


def j_cells(size):
    """[(x, y, 'L' | 'M')] for the size's J design."""
    (x0, y0), rows = J_PIXELS[size]
    return [(x0 + dx, y0 + dy, cell) for dy, row in enumerate(rows)
            for dx, cell in enumerate(row) if cell != "."]


def badge(size):
    cx, cy = BADGE_CENTRE[size]
    return cx, cy, BADGE_R * size, BADGE_OUTLINE * size


def check_badge(size):
    """The dot sits inside the frame and clears every J pixel."""
    cx, cy, r, _ = badge(size)
    if cx - r < 0 or cy - r < 0 or cx + r > size or cy + r > size:
        raise IconError(f"{size} px badge leaves the frame")
    for x, y, _cell in j_cells(size):
        nx, ny = min(max(cx, x), x + 1), min(max(cy, y), y + 1)
        if math.hypot(cx - nx, cy - ny) <= r:
            raise IconError(f"{size} px badge touches the J at ({x}, {y})")


def draw_frame(size, state):
    spec = STATES[state]
    canvas = Canvas(size)
    centre = size / 2.0
    canvas.shape(DISC, coverage(size, centre, centre, 0.0, centre))
    ring_r, ring_w = spec["ring_r"] * size, spec["ring_w"] * size
    canvas.shape(spec["ring"], coverage(size, centre, centre, ring_r - ring_w / 2,
                                        ring_r + ring_w / 2))
    if spec["badge"]:
        check_badge(size)
        cx, cy, r, outline = badge(size)
        canvas.shape(DISC, coverage(size, cx, cy, 0.0, r + outline / 2))
        canvas.shape(spec["badge"], coverage(size, cx, cy, 0.0, r - outline / 2))
    # The J goes last, in whole pixels: its colours stay exact in every state.
    for x, y, cell in j_cells(size):
        canvas.pixel(x, y, spec["light"] if cell == "L" else spec["rest"])
    return encode_png(size, size, canvas.rgba())


# --- Android ----------------------------------------------------------------------------
ADAPTIVE_ICON = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
    <monochrome android:drawable="@mipmap/ic_launcher_monochrome" />
</adaptive-icon>
"""

BACKGROUND_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">{ANDROID_BACKGROUND}</color>
</resources>
"""


# --- inputs -----------------------------------------------------------------------------
def required_renders():
    names = [f"emblem-{size}.png" for size in (*FULL_RENDERS, *SIMPLE_RENDERS)]
    for _density, size in ANDROID_DENSITIES:
        names += [f"android-foreground-{size}.png", f"android-monochrome-{size}.png"]
    return names


def render_size(name):
    return int(name.rsplit("-", 1)[1].split(".")[0])


def load_renders(root):
    """Reviewed render bytes, checked against the scene manifest and the current script."""
    where = paths(root)
    manifest_path = where["renders"] / f"{SCENE}.manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError) as error:
        raise IconError(f"No readable {SCENE} review manifest: run "
                        f"scripts/blender-build.py {SCENE} first ({error})") from error
    if not isinstance(manifest, dict) or manifest.get("scene") != SCENE \
            or manifest.get("format") != 1 or not isinstance(manifest.get("outputs"), dict):
        raise IconError(f"{manifest_path.name} is not a format 1 {SCENE} manifest")
    if not str(manifest.get("blender_version", "")).startswith("5.2."):
        raise IconError("The renders were not made with Blender 5.2.x")
    try:
        script_hash = sha256_bytes(where["scene"].read_bytes())
    except OSError as error:
        raise IconError(f"Missing scene script art/blender/{SCENE}.py") from error
    if manifest.get("generator_sha256") != script_hash:
        raise IconError(f"art/blender/{SCENE}.py changed since the renders: rebuild them")
    renders = {}
    for name in required_renders():
        record = manifest["outputs"].get(name)
        path = where["renders"] / name
        if not isinstance(record, dict) or not path.is_file():
            raise IconError(f"Render {name} is missing from the review")
        data = path.read_bytes()
        if sha256_bytes(data) != record.get("sha256") or len(data) != record.get("bytes"):
            raise IconError(f"Render {name} changed since review")
        size = render_size(name)
        width, height, depth, colour = png_info(data)
        if (width, height, depth, colour) != (size, size, 8, 6):
            raise IconError(f"Render {name} is not a {size}x{size} 8-bit RGBA PNG")
        renders[name] = data
    source = {
        "manifest": f".runtime/blender/review/{SCENE}.manifest.json",
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "generator": manifest.get("generator"),
        "generator_sha256": script_hash,
        "blender_version": manifest.get("blender_version"),
    }
    return renders, source


# --- build ------------------------------------------------------------------------------
def outputs(renders):
    """Every output as {relative path: bytes}."""
    frames = {(size, state): draw_frame(size, state) for state in STATES for size in TRAY_SIZES}
    emblem = {size: renders[f"emblem-{size}.png"] for size in (*FULL_RENDERS, *SIMPLE_RENDERS)}
    app_frames = [(size, frames[(size, "ready")] if size in PIXEL_SIZES else emblem[size])
                  for size in ICO_SIZES]
    files = {
        "jarvis.ico": encode_ico(app_frames),
        "jarvis.png": emblem[256],
        "setup/emblem-64.png": emblem[64],
        "setup/emblem-128.png": emblem[128],
        "android/res/mipmap-anydpi-v26/ic_launcher.xml": ADAPTIVE_ICON.encode(),
        "android/res/mipmap-anydpi-v26/ic_launcher_round.xml": ADAPTIVE_ICON.encode(),
        "android/res/values/ic_launcher_background.xml": BACKGROUND_XML.encode(),
    }
    for size in UI_MARKS:
        files[f"ui/mark-{size}.png"] = frames[(size, "ready")] if size in PIXEL_SIZES else emblem[size]
    for state in STATES:
        files[f"tray/jarvis-{state}.ico"] = encode_ico(
            [(size, frames[(size, state)]) for size in TRAY_SIZES])
    for density, size in ANDROID_DENSITIES:
        base = f"android/res/mipmap-{density}"
        files[f"{base}/ic_launcher_foreground.png"] = renders[f"android-foreground-{size}.png"]
        files[f"{base}/ic_launcher_monochrome.png"] = renders[f"android-monochrome-{size}.png"]
    return files


def describe(name, data):
    record = {"bytes": len(data), "sha256": sha256_bytes(data)}
    if name.endswith(".png"):
        width, height, _depth, _colour = png_info(data)
        record["pixels"] = [width, height]
    elif name.endswith(".ico"):
        (count,) = struct.unpack_from("<H", data, 4)
        record["frames"] = [data[6 + 16 * i] or 256 for i in range(count)]
    return record


def build(root):
    where = paths(root)
    out = where["out"]
    runtime = (root / ".runtime").resolve()
    if runtime not in out.resolve().parents:
        raise IconError("The review folder must sit under .runtime/")
    renders, source = load_renders(root)
    files = outputs(renders)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, data in sorted(files.items()):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        "format": 1,
        "generator": "scripts/build-icons.py",
        "generator_sha256": sha256_bytes(GENERATOR.read_bytes()),
        "source": source,
        "outputs": {name: describe(name, data) for name, data in sorted(files.items())},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8", newline="\n")
    print(f"{len(files)} file(s) for review in {out}")
    return manifest


# --- publish ----------------------------------------------------------------------------
def safe_name(value, prefixes=None):
    """A plain relative POSIX path (no drive, backslash, empty, '.' or '..' part)."""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 for c in value)
        or PurePosixPath(value).is_absolute()
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        return False
    return prefixes is None or value.startswith(prefixes)


def linked(base, relative):
    """True when any existing component from ``base`` down to ``relative`` is a link."""
    current = base
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink() or current.is_junction():
            return True
        if not current.exists():
            return False
    return False


def publish_targets(root):
    approvals = root / "art" / "icons" / "publish.json"
    if linked(root, "art/icons/publish.json"):
        raise IconError("art/icons/publish.json must not be a link")
    try:
        value = json.loads(approvals.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise IconError("No art/icons/publish.json: nothing is approved to publish") from error
    except (OSError, ValueError) as error:
        raise IconError(f"art/icons/publish.json is unreadable ({error})") from error
    if not isinstance(value, dict) or value.get("format") != 1 \
            or not isinstance(value.get("outputs"), dict) or not value["outputs"]:
        raise IconError("art/icons/publish.json is not a format 1 approvals file")
    targets, folded = value["outputs"], set()
    for output, target in targets.items():
        if not safe_name(output) or output == "manifest.json" \
                or not safe_name(target, PUBLISH_PREFIXES):
            raise IconError(f"Unsupported publish destination for {output!r}: {target!r}")
        if target.casefold() in folded:
            raise IconError(f"Two outputs are approved for {target}")
        folded.add(target.casefold())
    return targets


def publish(root):
    """Copy reviewed icon bytes, unchanged and without a rebuild, to approved destinations."""
    root = Path(root)
    base = root.resolve()
    where = paths(root)
    out = where["out"]
    targets = publish_targets(root)
    if linked(root, ".runtime/icons/review/manifest.json"):
        raise IconError("The icon review folder must not contain links")
    try:
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise IconError(f"Nothing reviewed: run scripts/build-icons.py first ({error})") from error
    if not isinstance(manifest, dict) or manifest.get("format") != 1 \
            or manifest.get("generator") != "scripts/build-icons.py" \
            or not isinstance(manifest.get("outputs"), dict) \
            or not isinstance(manifest.get("source"), dict):
        raise IconError("The icon review manifest is not a format 1 build-icons manifest")
    if manifest.get("generator_sha256") != sha256_bytes(GENERATOR.read_bytes()):
        raise IconError("scripts/build-icons.py changed since the review build: rebuild and "
                        "review again")
    source = manifest["source"]
    try:
        scene_hash = sha256_bytes(where["scene"].read_bytes())
    except OSError as error:
        raise IconError(f"Missing scene script art/blender/{SCENE}.py") from error
    if source.get("generator") != f"art/blender/{SCENE}.py" \
            or source.get("generator_sha256") != scene_hash:
        raise IconError(f"art/blender/{SCENE}.py changed since the review build: rebuild and "
                        "review again")
    if not str(source.get("blender_version", "")).startswith("5.2."):
        raise IconError("The reviewed renders were not made with Blender 5.2.x")
    # Check everything before copying anything.
    plan = []
    for output, target in sorted(targets.items()):
        record = manifest["outputs"].get(output)
        review = f".runtime/icons/review/{output}"
        if not isinstance(record, dict) or linked(root, review):
            raise IconError(f"Reviewed output {output} is missing or linked")
        path = root / review
        if not path.is_file() or not path.resolve().is_relative_to(out.resolve()):
            raise IconError(f"Reviewed output {output} is missing or outside the review folder")
        data = path.read_bytes()
        if sha256_bytes(data) != record.get("sha256") or len(data) != record.get("bytes"):
            raise IconError(f"Reviewed output {output} changed since review")
        destination = root / target
        if linked(root, target):
            raise IconError(f"Publish destination {target} goes through a link")
        if destination.resolve() != base / target or destination.is_dir():
            raise IconError(f"Publish destination {target} escapes the repository")
        plan.append((output, target, destination, data, record["sha256"]))
    entries = []
    origin = (f"owner-generated: scripts/build-icons.py (sha256 {manifest['generator_sha256']}) "
              f"from {source['generator']} (sha256 {source['generator_sha256']}), "
              f"Blender {source['blender_version']}")
    for output, target, destination, data, digest in plan:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if linked(root, target):
            raise IconError(f"Publish destination {target} goes through a link")
        destination.write_bytes(data)
        if sha256_bytes(destination.read_bytes()) != digest:
            raise IconError(f"Copy of {output} does not match its reviewed hash")
        print(f"published {output} -> {target}")
        if target.startswith(RENDERER_PREFIXES):
            entries.append({"path": target, "sha256": digest, "origin": origin, "owner": None,
                            "license_evidence": [], "decision": "pending"})
    print("Add to docs/ASSET_OWNERSHIP.json once the owner confirms:")
    print(json.dumps(entries, indent=2))
    return entries


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--publish", action="store_true",
                        help="copy reviewed icons to their approved repository locations")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        if args.publish:
            publish(root)
        else:
            build(root)
    except IconError as error:
        print(f"build-icons: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
