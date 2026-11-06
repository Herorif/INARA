"""JARVIS emblem: the crystal J inside the core's dial ring, on a dark disc (app icon).

Run through scripts/blender-build.py (headless, factory settings). Deterministic: no
random numbers, no clock-dependent names or metadata, CPU Cycles with a fixed seed,
sample count and filter, Standard view transform, stripped PNG metadata.

Scene arguments (after ``--``):
    --out DIR            output folder (set by blender-build.py)

Outputs (all RGBA PNG, transparent outside the artwork):
    emblem-<256|128|96|64|48>.png      full variant: ring, ticks, bead, ridge highlight
    emblem-<40|32>.png                 simplified: no ticks, ring 1.4/32 wide, no highlight
    android-foreground-<size>.png      J, ring and bead, no disc, 108-unit adaptive canvas
    android-monochrome-<size>.png      the same silhouette in flat white
    (Android sizes 108, 162, 216, 324, 432: mdpi to xxxhdpi.)

The design lives on a 256-unit grid (x right, y down, centre 128,128), the grid of the
approved SVG mockup. The camera is orthographic and head-on, so the grid maps straight to
the frame. Blender units: X = (x - 128) / 128, Y = (128 - y) / 128.
"""

import argparse
import math
from pathlib import Path
import struct
import sys
import time
import zlib

import bpy
from mathutils import Vector

# --- design constants (256 grid) -------------------------------------------------------
DISC = "#0A1017"
RING = "#2A8A96"
CYAN = "#70E0ED"              # ticks and bead
RIDGE = "#E6FBFD"             # ridge highlight
WHITE = "#FFFFFF"             # Android monochrome
TONES = ("#B0EFF5", "#8AE8F2", "#4FCFDD", "#34AEBD")   # facing the key light ... away

R_DISC = 124.0
R_RING, RING_WIDTH = 108.0, 3.0
RING_WIDTH_SIMPLE = 1.4 * 256 / 32          # 1.4 px at 32 px
TICK_SPAN, TICK_WIDTH = (100.0, 114.0), 3.0
BEAD_ANGLE = 40.0                           # degrees clockwise from top
R_BEAD = 6.0
R_BEAD_SIMPLE = 1.5 * 256 / 32              # the mockup's 32 px symbol (#A32): r 1.5 at 32
RIDGE_WIDTH = 1.6
RIDGE_HEIGHT = 10.0                         # the roof's rise above the contours

J_SHIFT = (-3.0, 0.0)
J_OUTER = ((175, 48), (175, 144), (169, 178), (149, 202), (119, 208), (93, 196), (81, 172))
J_INNER = ((145, 60), (145, 144), (141, 166), (131, 178), (117, 180), (105, 172), (103, 160))
J_RIDGE = ((160, 54), (160, 144), (155, 172), (140, 190), (118, 194), (99, 184), (92, 166))

# Facet tones, per stroke segment (0 = stem, 1-5 = hook to the tip): (inner, outer) index
# into TONES. A key light from the upper-left front lights the stem's left face and the
# hook's inner faces and leaves the outer faces darker; the tip faces are a step lighter.
# The table is the approved mockup's assignment (b2-inplace.html, #jf). No single fixed
# light direction reproduces it on this roof (the tip's inner faces point up-right yet
# read lighter than the hook's left-facing ones), so the tones are fixed per facet rather
# than computed from a light at render time.
FACET_TONES = ((0, 2), (1, 3), (1, 3), (1, 3), (0, 2), (0, 2))

FULL_SIZES = (256, 128, 96, 64, 48)
SIMPLE_SIZES = (40, 32)
ANDROID_SIZES = (108, 162, 216, 324, 432)
ANDROID_CANVAS, ANDROID_SAFE = 108.0, 66.0
ANDROID_EXTENT = 32.0       # the bead's outer edge sits 1 unit inside the 33-unit safe radius
SAMPLES = 256

# Draw order (orthographic, looking down -Z): higher Z is in front.
Z_DISC, Z_RING, Z_TICK, Z_BEAD, Z_J = 0.0, 0.001, 0.002, 0.003, 0.01


# --- colour -----------------------------------------------------------------------------
def srgb_to_linear(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def linear(code):
    code = code.lstrip("#")
    return (*[srgb_to_linear(int(code[i:i + 2], 16) / 255.0) for i in (0, 2, 4)], 1.0)


# --- geometry ---------------------------------------------------------------------------
def grid(x, y, z=0.0):
    """256-grid point (y down) to Blender units (Y up)."""
    return ((x - 128.0) / 128.0, (128.0 - y) / 128.0, z)


def polar(radius, degrees_clockwise_from_top):
    a = math.radians(degrees_clockwise_from_top)
    return 128.0 + radius * math.sin(a), 128.0 - radius * math.cos(a)


def disc_mesh(cx, cy, radius, z, segments=256):
    verts = [grid(cx + radius * math.cos(2 * math.pi * i / segments),
                  cy + radius * math.sin(2 * math.pi * i / segments), z)
             for i in range(segments)]
    return verts, [tuple(range(segments))]


def annulus_mesh(radius, width, z, segments=256):
    inner, outer = radius - width / 2.0, radius + width / 2.0
    verts = []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        verts.append(grid(128 + inner * math.cos(a), 128 + inner * math.sin(a), z))
        verts.append(grid(128 + outer * math.cos(a), 128 + outer * math.sin(a), z))
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((2 * i, 2 * j, 2 * j + 1, 2 * i + 1))
    return verts, faces


def ticks_mesh(z):
    verts, faces = [], []
    lo, hi = TICK_SPAN
    h = TICK_WIDTH / 2.0
    for angle in (0.0, 90.0, 180.0, 270.0):
        a = math.radians(angle)
        along, across = (math.sin(a), -math.cos(a)), (math.cos(a), math.sin(a))
        base = len(verts)
        for r, s in ((lo, -h), (hi, -h), (hi, h), (lo, h)):
            verts.append(grid(128 + along[0] * r + across[0] * s,
                              128 + along[1] * r + across[1] * s, z))
        faces.append((base, base + 1, base + 2, base + 3))
    return verts, faces


def shifted(points):
    return [(x + J_SHIFT[0], y + J_SHIFT[1]) for x, y in points]


def j_mesh():
    """The chiselled J: a roof whose ridge runs along the stroke, falling to both edges.

    Vertices: ridge points at Z_J + rise, outer and inner contour points at Z_J. Faces:
    one sloped face per segment and side (materials from FACET_TONES), the two end caps
    and the flat base.
    """
    rise = RIDGE_HEIGHT / 128.0
    ridge, outer, inner = shifted(J_RIDGE), shifted(J_OUTER), shifted(J_INNER)
    n = len(ridge)
    verts = ([grid(x, y, Z_J + rise) for x, y in ridge] + [grid(x, y, Z_J) for x, y in outer]
             + [grid(x, y, Z_J) for x, y in inner])
    r, o, i = 0, n, 2 * n
    faces, tones = [], []
    for k in range(n - 1):
        inner_tone, outer_tone = FACET_TONES[k]
        faces.append((r + k, i + k, i + k + 1, r + k + 1))
        tones.append(inner_tone)
        faces.append((r + k, r + k + 1, o + k + 1, o + k))
        tones.append(outer_tone)
    caps = [(i, r, o), (o + n - 1, r + n - 1, i + n - 1)]          # top cut, tip cut
    base = tuple([o + k for k in range(n)] + [i + k for k in reversed(range(n))])
    faces += caps + [base]
    tones += [None, None, None]
    return verts, faces, tones


def ribbon_mesh(points, width, z, join_segments=16):
    """A flat stroke along a polyline: butt ends, round joins (SVG stroke-linejoin round)."""
    h = width / 2.0
    verts, faces = [], []
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        nx, ny = -dy / length * h, dx / length * h
        base = len(verts)
        verts += [grid(x0 + nx, y0 + ny, z), grid(x1 + nx, y1 + ny, z),
                  grid(x1 - nx, y1 - ny, z), grid(x0 - nx, y0 - ny, z)]
        faces.append((base, base + 1, base + 2, base + 3))
    for x, y in points[1:-1]:
        d_verts, d_faces = disc_mesh(x, y, h, z, join_segments)
        base = len(verts)
        verts += d_verts
        faces += [tuple(base + v for v in face) for face in d_faces]
    return verts, faces


# --- scene ------------------------------------------------------------------------------
def emission_material(name, code):
    mat = bpy.data.materials.new(name)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = linear(code)
    emit.inputs["Strength"].default_value = 1.0
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def add_object(scene, name, verts, faces, materials, face_materials=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    for mat in materials:
        mesh.materials.append(mat)
    if face_materials is not None:
        for poly, index in zip(mesh.polygons, face_materials, strict=True):
            poly.material_index = index
    mesh.shade_flat()
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    return obj


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    mats = {code: emission_material(f"emit_{code.lstrip('#').lower()}", code)
            for code in (DISC, RING, CYAN, RIDGE, WHITE, *TONES)}
    bead_x, bead_y = polar(R_RING, BEAD_ANGLE)
    objects = {
        "disc": add_object(scene, "disc", *disc_mesh(128, 128, R_DISC, Z_DISC), [mats[DISC]]),
        "ring": add_object(scene, "ring", *annulus_mesh(R_RING, RING_WIDTH, Z_RING),
                           [mats[RING]]),
        "ring_simple": add_object(scene, "ring_simple",
                                  *annulus_mesh(R_RING, RING_WIDTH_SIMPLE, Z_RING),
                                  [mats[RING]]),
        "ticks": add_object(scene, "ticks", *ticks_mesh(Z_TICK), [mats[CYAN]]),
        "bead": add_object(scene, "bead", *disc_mesh(bead_x, bead_y, R_BEAD, Z_BEAD, 64),
                           [mats[CYAN]]),
        "bead_simple": add_object(scene, "bead_simple",
                                  *disc_mesh(bead_x, bead_y, R_BEAD_SIMPLE, Z_BEAD, 64),
                                  [mats[CYAN]]),
    }
    verts, faces, tones = j_mesh()
    # Caps and base never face the camera; they take the darkest tone.
    objects["j"] = add_object(scene, "j", verts, faces, [mats[code] for code in TONES],
                              [len(TONES) - 1 if t is None else t for t in tones])
    rise = RIDGE_HEIGHT / 128.0
    objects["ridge"] = add_object(scene, "ridge",
                                  *ribbon_mesh(shifted(J_RIDGE), RIDGE_WIDTH,
                                               Z_J + rise + 0.01),
                                  [mats[RIDGE]])
    return scene, objects, mats


def configure_render(scene):
    scene.render.engine = "CYCLES"
    cycles = scene.cycles
    cycles.device = "CPU"
    cycles.seed = 0
    cycles.use_animated_seed = False
    cycles.use_adaptive_sampling = False
    cycles.samples = SAMPLES
    cycles.use_denoising = False          # flat emission: nothing to denoise
    cycles.max_bounces = 0
    cycles.caustics_reflective = cycles.caustics_refractive = False
    cycles.use_light_tree = False
    # A one-pixel box filter: each pixel is the exact area coverage of the artwork, so
    # edges stay crisp at every size without aliasing.
    cycles.pixel_filter_type = "BOX"
    cycles.filter_width = 1.0
    scene.render.film_transparent = True
    scene.render.dither_intensity = 0.0
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    for prop in dir(scene.render):
        if prop.startswith("use_stamp"):
            setattr(scene.render, prop, False)
    settings = scene.render.image_settings
    settings.file_format = "PNG"
    settings.color_mode = "RGBA"
    settings.color_depth = "8"
    settings.compression = 90
    scene.display_settings.display_device = "sRGB"
    view = scene.view_settings
    view.view_transform = "Standard"      # brand hex values come out exact
    view.look = "None"
    view.exposure = 0.0
    view.gamma = 1.0
    world = bpy.data.worlds.new("void")
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    scene.world = world


def make_camera(scene):
    data = bpy.data.cameras.new("camera")
    data.type = "ORTHO"
    data.clip_start, data.clip_end = 0.1, 100.0
    cam = bpy.data.objects.new("camera", data)
    scene.collection.objects.link(cam)
    cam.location = Vector((0.0, 0.0, 10.0))     # head-on, looking down -Z, up +Y
    cam.rotation_euler = (0.0, 0.0, 0.0)
    scene.camera = cam
    return cam


PNG_KEEP = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"cHRM", b"pHYs"}
PNG_MAGIC = bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A))


def strip_png_metadata(path):
    """Drop text/EXIF chunks: Cycles writes render timings into them."""
    raw = Path(path).read_bytes()
    if raw[:8] != PNG_MAGIC:
        raise RuntimeError(f"{path} is not a PNG")
    out, offset = [raw[:8]], 8
    while offset < len(raw):
        length, kind = struct.unpack_from(">I4s", raw, offset)
        chunk = raw[offset:offset + 12 + length]
        if zlib.crc32(chunk[4:8 + length]) != struct.unpack_from(">I", chunk, 8 + length)[0]:
            raise RuntimeError(f"{path}: bad PNG chunk CRC")
        if kind in PNG_KEEP:
            out.append(chunk)
        offset += 12 + length
    Path(path).write_bytes(b"".join(out))


def render(scene, cam, path, size, ortho_scale, visible, objects, override=None):
    for name, obj in objects.items():
        obj.hide_render = name not in visible
    bpy.context.view_layer.material_override = override
    cam.data.ortho_scale = ortho_scale
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(path)
    start = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    strip_png_metadata(path)
    print(f"rendered {path.name} {size}x{size} @{SAMPLES} spp in "
          f"{time.perf_counter() - start:.2f}s")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="jarvis-emblem")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    scene, objects, mats = build_scene()
    configure_render(scene)
    cam = make_camera(scene)

    full = {"disc", "ring", "ticks", "bead", "j", "ridge"}
    simple = {"disc", "ring_simple", "bead_simple", "j"}
    android = {"ring", "bead", "j", "ridge"}
    silhouette = {"ring", "bead", "j"}
    emblem_scale = 2.0                                       # the 256 grid fills the frame
    # Adaptive icons: a 108-unit canvas with a 66-unit safe zone. The bead's outer edge
    # (R_RING + R_BEAD grid units from the centre) lands ANDROID_EXTENT units out.
    extent = R_RING + R_BEAD
    if not ANDROID_EXTENT <= ANDROID_SAFE / 2.0:
        raise RuntimeError("the Android artwork must sit inside the safe zone")
    android_scale = (ANDROID_CANVAS / ANDROID_EXTENT) * extent / 128.0

    for size in FULL_SIZES:
        render(scene, cam, out / f"emblem-{size}.png", size, emblem_scale, full, objects)
    for size in SIMPLE_SIZES:
        render(scene, cam, out / f"emblem-{size}.png", size, emblem_scale, simple, objects)
    for size in ANDROID_SIZES:
        render(scene, cam, out / f"android-foreground-{size}.png", size, android_scale,
               android, objects)
    for size in ANDROID_SIZES:
        render(scene, cam, out / f"android-monochrome-{size}.png", size, android_scale,
               silhouette, objects, override=mats[WHITE])


main()
