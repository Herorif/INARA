"""JARVIS core: a thin-line armillary instrument. GLB for the app plus review stills.

Run through scripts/blender-build.py (headless, factory settings). Deterministic: no
random numbers, no clock-dependent names or metadata, fixed samples and seed.

Scene arguments (after ``--``):
    --out DIR            output folder (set by blender-build.py)
    --only all|glb|hero|states
    --device CPU|auto|OPTIX|CUDA   (CPU by default: byte-identical renders)

Coordinates are Blender Z-up; the camera looks along +Y, so a ring in the local XZ plane
faces it. The glTF exporter converts to Y-up (local XZ becomes glTF XY, facing a three.js
camera on +Z).
"""

import argparse
import json
import math
from pathlib import Path
import struct
import sys
import time
import zlib

import bmesh
import bpy
from mathutils import Vector

# --- design constants -----------------------------------------------------------------
BACKGROUND = "#05080C"
CYAN = "#70E0ED"
STEEL = "#5B6B73"
FACE = "#0A1418"
FACE_OFFLINE = "#0C0F11"
SECONDARY_STRENGTH = 0.35   # display-space mix toward the background
OFFLINE_STRENGTH = 0.50

R_OUTER, R_ARC, R_MID, R_INNER, R_CORE = 1.00, 1.06, 0.80, 0.60, 0.17
RETICLE = (1.12, 1.20)
TICK_MINOR, TICK_MAJOR = 0.035, 0.070
TILT_MID, TILT_INNER = 62.0, -48.0          # about X, about Z (glTF Y)
TUBE_OUTER, TUBE_LINE = 0.0035, 0.0025
BEAD_EDGE = 0.024                           # solid cube markers on the middle ring
EDGE_LIFT = 1.004                           # core edges sit just outside the faces

# Default view for every still and for the app: camera orbit around the origin.
# Blender: camera at d*(cos el*sin az, -cos el*cos az, sin el) looking at the origin.
# glTF/three.js (Y-up): camera at d*(cos el*sin az, sin el, cos el*cos az), up +Y.
DEFAULT_VIEW = {"azimuth": 24.0, "elevation": 12.0}
LOCK_VIEW = {"azimuth": 20.0, "elevation": 10.0}   # a touch calmer, still a diagonal orbit
LENS_MM, SENSOR_MM = 100.0, 36.0                   # square frames: vertical FOV 20.41 deg

NODES = ("ring_outer", "ticks_minor", "ticks_major", "arc_band", "ring_mid", "beads",
         "ring_inner", "core_edges", "core_faces", "reticle")
FACE_NODES = {"core_faces", "beads"}               # triangles; every other node is LINES
PRIMARY = {"ring_outer", "ticks_major", "ring_mid", "core_edges"}

# Static poses for review stills. The app animates between them later.
STATES = {
    "idle": {"mid_spin": 10.0, "inner_spin": -6.0, "arc_spin": 0.0},
    "listening": {"tilt_mid": TILT_MID * 0.35, "tilt_inner": TILT_INNER * 0.35,
                  "arc": "primary"},
    "speaking": {"core_scale": 1.08, "arc": "primary"},
    "working": {"arc_spin": 40.0, "inner_spin": 7.5},
    "offline": {"offline": True},
}

SAMPLES = {"hero": 128, "state": 64}


def srgb_to_linear(value):
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def hex_srgb(code):
    code = code.lstrip("#")
    return tuple(int(code[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def linear(code, strength=1.0, over=BACKGROUND):
    """Display-space mix of `code` over the background, as linear RGBA."""
    fg, bg = hex_srgb(code), hex_srgb(over)
    mixed = [b + strength * (f - b) for f, b in zip(fg, bg, strict=True)]
    return (*[srgb_to_linear(c) for c in mixed], 1.0)


# --- geometry -------------------------------------------------------------------------
def on_plane(radius, degrees):
    a = math.radians(degrees)
    return (radius * math.cos(a), 0.0, radius * math.sin(a))


def circle(radius, segments):
    verts = [on_plane(radius, 360.0 * i / segments) for i in range(segments)]
    edges = [(i, (i + 1) % segments) for i in range(segments)]
    return verts, edges


def polyline_arcs(radius, arcs, step):
    """`arcs` are (start, end) degrees; each becomes an open polyline."""
    verts, edges = [], []
    for start, end in arcs:
        count = max(1, round((end - start) / step))
        base = len(verts)
        verts += [on_plane(radius, start + (end - start) * i / count) for i in range(count + 1)]
        edges += [(base + i, base + i + 1) for i in range(count)]
    return verts, edges


def radial_segments(angles, inner, outer):
    verts, edges = [], []
    for angle in angles:
        verts += [on_plane(inner, angle), on_plane(outer, angle)]
        edges.append((len(verts) - 2, len(verts) - 1))
    return verts, edges


def cubes(centers, edge):
    """Solid cubes (outward-facing quads) centred on points of the ring's local plane."""
    verts, faces = [], []
    h = edge / 2.0
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6),
             (3, 0, 4, 7)]
    for x, z in centers:
        base = len(verts)
        verts += [(x + dx, dy, z + dz) for dz in (-h, h)
                  for dx, dy in ((-h, -h), (h, -h), (h, h), (-h, h))]
        faces += [tuple(base + i for i in quad) for quad in quads]
    return verts, faces


def view_direction(view):
    az, el = math.radians(view["azimuth"]), math.radians(view["elevation"])
    return Vector((math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el)))


def icosahedron():
    """Base icosahedron (20 faces, 30 edges), turned so a face meets the default view."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=R_CORE)
    bm.faces.ensure_lookup_table()
    # The face whose normal is nearest the default view is turned to face it exactly:
    # no vertex points at the camera and the silhouette is a clean hexagon of facets.
    to_camera = view_direction(DEFAULT_VIEW)
    face = max(bm.faces, key=lambda f: (round(f.normal.dot(to_camera), 9), -f.index))
    turn = face.normal.rotation_difference(to_camera).to_matrix()
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=turn)
    bm.verts.index_update()
    verts = [tuple(round(c, 6) for c in v.co) for v in bm.verts]
    faces = [tuple(v.index for v in f.verts) for f in bm.faces]
    edges = [tuple(v.index for v in e.verts) for e in bm.edges]
    bm.free()
    if len(faces) != 20 or len(edges) != 30:
        raise RuntimeError("unexpected icosahedron topology")
    return verts, edges, faces


def geometry():
    ticks = [5.0 * i for i in range(72)]
    arcs = [(c - 19.0, c + 19.0) for c in (90.0, 210.0, 330.0)]
    dashes = [(15.0 * k - 4.5, 15.0 * k + 4.5) for k in range(24)]
    core_v, core_e, core_f = icosahedron()
    return {
        "ring_outer": circle(R_OUTER, 192),
        "ticks_minor": radial_segments([a for i, a in enumerate(ticks) if i % 6],
                                       R_OUTER - TICK_MINOR, R_OUTER),
        "ticks_major": radial_segments([a for i, a in enumerate(ticks) if not i % 6],
                                       R_OUTER - TICK_MAJOR, R_OUTER),
        "arc_band": polyline_arcs(R_ARC, arcs, 1.0),
        "ring_mid": circle(R_MID, 160),
        "beads": cubes([(R_MID, 0.0), (-R_MID, 0.0)], BEAD_EDGE),
        "ring_inner": polyline_arcs(R_INNER, dashes, 3.0),
        "core_edges": ([tuple(c * EDGE_LIFT for c in v) for v in core_v], core_e),
        "core_faces": (core_v, core_f),
        "reticle": radial_segments([0.0, 90.0, 180.0, 270.0], *RETICLE),
    }


# --- scene ----------------------------------------------------------------------------
def gltf_material(name, color, alpha=1.0, emissive=True, roughness=1.0):
    mat = bpy.data.materials.new(name)
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    rgba = (*[srgb_to_linear(c) for c in hex_srgb(color)], 1.0)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Alpha"].default_value = alpha
    if emissive:
        bsdf.inputs["Emission Color"].default_value = rgba
        bsdf.inputs["Emission Strength"].default_value = 1.0
    if alpha < 1.0 and hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    return mat


def build_rig():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    mats = {
        "line_primary": gltf_material("line_primary", CYAN),
        "line_secondary": gltf_material("line_secondary", CYAN, alpha=SECONDARY_STRENGTH),
        "core_face": gltf_material("core_face", FACE, emissive=False, roughness=0.6),
        "bead_face": gltf_material("bead_face", CYAN),
    }
    root = bpy.data.objects.new("jarvis_core", None)
    scene.collection.objects.link(root)
    objects = {}
    for name, (verts, links) in geometry().items():
        mesh = bpy.data.meshes.new(name)
        if name in FACE_NODES:
            mesh.from_pydata(verts, [], links)
            mesh.shade_flat()
        else:
            mesh.from_pydata(verts, links, [])
        mesh.update()
        material = ("core_face" if name == "core_faces" else "bead_face" if name == "beads"
                    else "line_primary" if name in PRIMARY else "line_secondary")
        mesh.materials.append(mats[material])
        obj = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(obj)
        obj.parent = root
        obj.rotation_mode = "YXZ"   # spin in the ring's own plane first, then tilt
        objects[name] = obj
    objects["beads"].parent = objects["ring_mid"]   # beads ride on the middle ring
    pose(objects, {})
    return objects


def pose(objects, state):
    mid = objects["ring_mid"]
    mid.rotation_euler = (math.radians(state.get("tilt_mid", TILT_MID)),
                          math.radians(state.get("mid_spin", 0.0)), 0.0)
    inner = objects["ring_inner"]
    inner.rotation_euler = (0.0, math.radians(state.get("inner_spin", 0.0)),
                            math.radians(state.get("tilt_inner", TILT_INNER)))
    objects["arc_band"].rotation_euler = (0.0, math.radians(state.get("arc_spin", 0.0)), 0.0)
    scale = state.get("core_scale", 1.0)
    for name in ("core_edges", "core_faces"):
        objects[name].scale = (scale, scale, scale)
    bpy.context.view_layer.update()


# --- GLB export and self-check --------------------------------------------------------
def export_glb(path):
    bpy.ops.export_scene.gltf(
        filepath=str(path), export_format="GLB", use_selection=False,
        export_yup=True, export_apply=False, use_mesh_edges=True, use_mesh_vertices=False,
        export_texcoords=False, export_normals=True, export_tangents=False,
        export_materials="EXPORT", export_image_format="NONE", export_vertex_color="NONE",
        export_attributes=False, export_cameras=False, export_lights=False,
        export_extras=False, export_animations=False, export_morph=False,
        export_skins=False, export_draco_mesh_compression_enable=False,
        export_meshopt_compression_enable=False, export_use_gltfpack=False,
        export_copyright="",
    )
    return check_glb(path)


def check_glb(path):
    raw = Path(path).read_bytes()
    magic, version, length = struct.unpack_from("<4sII", raw, 0)
    chunk_length, chunk_type = struct.unpack_from("<I4s", raw, 12)
    if magic != b"glTF" or version != 2 or length != len(raw) or chunk_type != b"JSON":
        raise RuntimeError("not a glTF 2 binary")
    gltf = json.loads(raw[20:20 + chunk_length])
    names = {node["name"]: node for node in gltf["nodes"]}
    missing = [n for n in NODES if n not in names]
    if missing:
        raise RuntimeError(f"GLB lacks nodes {missing}")
    for name in NODES:
        prims = gltf["meshes"][names[name]["mesh"]]["primitives"]
        modes = {p.get("mode", 4) for p in prims}
        want = {4} if name in FACE_NODES else {1}
        if modes != want:
            raise RuntimeError(f"{name}: primitive modes {modes}, expected {want}")
    materials = sorted(m["name"] for m in gltf.get("materials", []))
    if materials != ["bead_face", "core_face", "line_primary", "line_secondary"]:
        raise RuntimeError(f"unexpected materials {materials}")
    forbidden = {"images", "textures", "samplers"} & set(gltf)
    used = set(gltf.get("extensionsUsed", []))
    if forbidden or "KHR_draco_mesh_compression" in used:
        raise RuntimeError(f"GLB carries textures or Draco: {forbidden | used}")
    if len(raw) > 150 * 1024:
        raise RuntimeError(f"GLB is {len(raw)} bytes, over the 150 KB budget")
    print(f"GLB {path.name}: {len(raw)} bytes, nodes {[n['name'] for n in gltf['nodes']]}")
    print(f"GLB extensions {sorted(used)}")
    return gltf


# --- rendering ------------------------------------------------------------------------
def emission_material(name, rgba):
    mat = bpy.data.materials.new(name)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = rgba
    emit.inputs["Strength"].default_value = 1.0
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def facet_material(name, code):
    """Self-lit facet shading: brightness from the flat normal against a fixed key."""
    mat = bpy.data.materials.new(name)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    geo = nodes.new("ShaderNodeNewGeometry")
    key = nodes.new("ShaderNodeCombineXYZ")
    direction = Vector((-0.45, -0.65, 0.62)).normalized()
    for axis, value in zip("XYZ", direction, strict=True):
        key.inputs[axis].default_value = value
    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = -1.0
    ramp.inputs["From Max"].default_value = 1.0
    ramp.inputs["To Min"].default_value = 0.55
    ramp.inputs["To Max"].default_value = 2.4
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = linear(code)
    links.new(geo.outputs["True Normal"], dot.inputs[0])
    links.new(key.outputs["Vector"], dot.inputs[1])
    links.new(dot.outputs["Value"], ramp.inputs["Value"])
    links.new(ramp.outputs["Result"], emit.inputs["Strength"])
    links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def tube_modifier(obj, radius, material):
    """Loose edges -> thin round tubes (render only; the GLB keeps the edges)."""
    group = bpy.data.node_groups.new(f"tube_{obj.name}", "GeometryNodeTree")
    group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = group.nodes, group.links
    gin = nodes.new("NodeGroupInput")
    gout = nodes.new("NodeGroupOutput")
    to_curve = nodes.new("GeometryNodeMeshToCurve")
    profile = nodes.new("GeometryNodeCurvePrimitiveCircle")
    profile.inputs["Resolution"].default_value = 8
    profile.inputs["Radius"].default_value = radius
    to_mesh = nodes.new("GeometryNodeCurveToMesh")
    setmat = nodes.new("GeometryNodeSetMaterial")
    setmat.name = "material"
    setmat.inputs["Material"].default_value = material
    links.new(gin.outputs[0], to_curve.inputs["Mesh"])
    links.new(to_curve.outputs["Curve"], to_mesh.inputs["Curve"])
    links.new(profile.outputs["Curve"], to_mesh.inputs["Profile Curve"])
    links.new(to_mesh.outputs["Mesh"], setmat.inputs["Geometry"])
    links.new(setmat.outputs["Geometry"], gout.inputs[0])
    modifier = obj.modifiers.new("tube", "NODES")
    modifier.node_group = group
    return setmat


def probe_render(scene):
    """A 16x16, 1-sample render: GPU backends can enumerate yet fail to load kernels."""
    saved = (scene.render.resolution_x, scene.render.resolution_y, scene.cycles.samples)
    scene.render.resolution_x = scene.render.resolution_y = 16
    scene.cycles.samples = 1
    try:
        bpy.ops.render.render(write_still=False)
        return True
    except RuntimeError as error:
        print(f"device probe failed: {str(error).splitlines()[0]}")
        return False
    finally:
        scene.render.resolution_x, scene.render.resolution_y, scene.cycles.samples = saved


def choose_device(scene, wanted):
    """OPTIX, then CUDA, then CPU; each GPU backend must pass a probe render."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    order = ["OPTIX", "CUDA"] if wanted == "auto" else [wanted]
    for kind in order:
        if kind == "CPU":
            break
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.refresh_devices()
        gpus = [d for d in prefs.devices if d.type == kind]
        if not gpus:
            continue
        for device in prefs.devices:
            device.use = device.type == kind
        scene.cycles.device = "GPU"
        if not probe_render(scene):
            if wanted != "auto":
                raise RuntimeError(f"render device {kind} is not usable")
            continue
        print(f"render device {kind}: {[d.name for d in gpus]}")
        return kind
    prefs.compute_device_type = "NONE"
    scene.cycles.device = "CPU"
    print("render device CPU")
    return "CPU"


def configure_render(scene):
    scene.render.engine = "CYCLES"
    cycles = scene.cycles
    cycles.seed = 0
    cycles.use_animated_seed = False
    cycles.use_adaptive_sampling = False
    cycles.use_denoising = True
    cycles.denoiser = "OPENIMAGEDENOISE"
    cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    cycles.denoising_prefilter = "ACCURATE"
    if hasattr(cycles, "denoising_quality"):
        cycles.denoising_quality = "HIGH"
    if hasattr(cycles, "denoising_use_gpu"):
        cycles.denoising_use_gpu = False   # CPU OIDN: same result on every run
    cycles.max_bounces = 0
    cycles.caustics_reflective = cycles.caustics_refractive = False
    cycles.filter_width = 1.2
    cycles.use_light_tree = False
    scene.render.film_transparent = False
    scene.render.dither_intensity = 0.0    # flat, exact #05080C background
    scene.render.use_compositing = False   # no glare, bloom or other compositing
    scene.render.use_sequencer = False
    for prop in dir(scene.render):
        if prop.startswith("use_stamp"):
            setattr(scene.render, prop, False)
    settings = scene.render.image_settings
    settings.file_format = "PNG"
    settings.color_mode = "RGB"
    settings.color_depth = "8"
    settings.compression = 90
    view = scene.view_settings
    scene.display_settings.display_device = "sRGB"
    view.view_transform = "Standard"   # brand hex values come out exact
    view.look = "None"
    view.exposure = 0.0
    view.gamma = 1.0
    world = bpy.data.worlds.new("console")
    world.node_tree.nodes["Background"].inputs["Color"].default_value = linear(BACKGROUND)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    scene.world = world


def make_camera(scene):
    data = bpy.data.cameras.new("camera")
    data.lens = LENS_MM
    data.sensor_fit = "AUTO"
    data.sensor_width = SENSOR_MM
    data.clip_start, data.clip_end = 0.1, 200.0
    cam = bpy.data.objects.new("camera", data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def frame(cam, scene, width, height, view, radius_px, center_y=0.5):
    """Orbit the camera so a 1.2-unit rig fills `radius_px`; centre at `center_y` of height."""
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    data = cam.data
    long_side = max(width, height)
    half_height_mm = data.sensor_width * height / long_side / 2.0
    visible_half = RETICLE[1] * (height / 2.0) / radius_px
    distance = visible_half * data.lens / half_height_mm
    cam.location = view_direction(view) * distance
    cam.rotation_mode = "XYZ"
    cam.rotation_euler = (Vector((0, 0, 0)) - Vector(cam.location)).to_track_quat(
        "-Z", "Y").to_euler()
    data.shift_x = 0.0
    data.shift_y = (center_y - 0.5) * height / long_side


PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"cHRM", b"pHYs"}
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


def render(scene, path, samples):
    scene.cycles.samples = samples
    scene.render.filepath = str(path)
    start = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    strip_png_metadata(path)
    print(f"rendered {path.name} {scene.render.resolution_x}x{scene.render.resolution_y} "
          f"@{samples} spp in {time.perf_counter() - start:.2f}s")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="jarvis-core")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--only", choices=("all", "glb", "hero", "states"), default="all")
    parser.add_argument("--device", choices=("CPU", "auto", "OPTIX", "CUDA"), default="CPU")
    args = parser.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    objects = build_rig()
    export_glb(out / "jarvis-core.glb")
    if args.only == "glb":
        return

    scene = bpy.context.scene
    configure_render(scene)
    cam = make_camera(scene)
    choose_device(scene, args.device)
    looks = {
        "primary": emission_material("render_primary", linear(CYAN)),
        "secondary": emission_material("render_secondary", linear(CYAN, SECONDARY_STRENGTH)),
        "offline": emission_material("render_offline", linear(STEEL, OFFLINE_STRENGTH)),
        "face": facet_material("render_face", FACE),
        "face_offline": facet_material("render_face_offline", FACE_OFFLINE),
    }
    setters = {}
    for name in NODES:
        if name in FACE_NODES:
            continue
        radius = TUBE_OUTER if name == "ring_outer" else TUBE_LINE
        look = "primary" if name in PRIMARY else "secondary"
        setters[name] = tube_modifier(objects[name], radius, looks[look])

    def apply(state_name):
        state = STATES[state_name]
        pose(objects, state)
        for name, setter in setters.items():
            look = "primary" if name in PRIMARY else "secondary"
            if name == "arc_band" and state.get("arc") == "primary":
                look = "primary"
            if state.get("offline"):
                look = "offline"
            setter.inputs["Material"].default_value = looks[look]
        face = looks["face_offline" if state.get("offline") else "face"]
        objects["core_faces"].data.materials[0] = face
        objects["beads"].data.materials[0] = looks["offline" if state.get("offline")
                                                   else "primary"]

    if args.only in ("all", "hero"):
        apply("idle")
        frame(cam, scene, 1920, 1080, DEFAULT_VIEW, radius_px=370)
        render(scene, out / "hero-splash-1920x1080.png", SAMPLES["hero"])
        frame(cam, scene, 1440, 900, LOCK_VIEW, radius_px=225, center_y=0.40)
        render(scene, out / "hero-lock-1440x900.png", SAMPLES["hero"])
    if args.only in ("all", "states"):
        for state_name in STATES:
            apply(state_name)
            frame(cam, scene, 512, 512, DEFAULT_VIEW, radius_px=228)
            render(scene, out / f"state-{state_name}-512.png", SAMPLES["state"])


main()
