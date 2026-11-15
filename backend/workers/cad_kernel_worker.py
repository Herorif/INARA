"""The JARVIS CAD kernel worker: feature trees to build123d geometry, as JSON lines.

Runs as ``.venv-cad\\Scripts\\python.exe -I cad_kernel_worker.py`` with the working directory
set to the core's temp job folder. It never imports the core's modules (different
interpreter) and never uses the network: it gets an already-validated, canonical tree
(``services.cad_features.canonical``) and interprets it. Conventions are the ones documented
in ``backend/services/cad_features.py``.

Protocol: one JSON object per line on stdin, one reply per line on stdout, matched by ``id``.
- ``{"id", "cmd": "ping"}`` -> ``{"id", "ok": true, "version"}``
- ``{"id", "cmd": "build", "tree", "export": [...], "quality": "draft"|"final", "folder"}``
  -> ``{"id", "ok": true, "facts": {volume, bbox, faces, edges, valid}, "files": {ext: path},
  "warnings": [{code, index, feature}], "seconds"}`` or ``{"id", "ok": false, "code",
  "message", "feature", "index", "detail"}``. ``folder`` is a plain name; files go to ``<cwd>/<folder>/model.<ext>``.
- ``{"id", "cmd": "exit"}`` ends the worker.

OpenCascade can print to the C-level stdout, so the protocol uses a private duplicate of the
original stdout and file descriptor 1 is pointed at stderr.
"""

import json
import math
import os
import re
import sys
import time
from pathlib import Path

MAX_REQUEST = 1024 * 1024
M = 0.5  # mm a cutting tool starts outside the face, so booleans never meet coplanar faces
EMBED = 0.01  # mm an embossed feature sinks into its face, so the union overlaps
FOLDER = re.compile(r"[A-Za-z0-9_-]{1,64}")
SOLID_OPS = ("box", "cylinder", "sphere", "l_bracket", "enclosure")
FACE_OPS = ("hole", "slot", "text")
CHANGES = ("hole", "slot", "text", "cut", "union", "pattern", "mirror")
EXPORTS = ("glb", "stl", "step")
# Relative deflections (OpenCascade meshes relative to each edge's size).
QUALITY = {
    "draft": {"linear": 0.05, "angular": 0.5},
    "final": {"linear": 0.001, "angular": 0.1},
}
# Outward normal N, then the face axes U and V of each face (cad_features conventions).
FACES = {
    "top": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    "bottom": ((0, 0, -1), (1, 0, 0), (0, 1, 0)),
    "front": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    "back": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "left": ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "right": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
}
# Text reads left to right seen from outside the face, with this direction up.
TEXT_UP = {"top": (0, 1, 0), "bottom": (0, -1, 0)}

b3d = None  # build123d, imported in main()


class KernelError(Exception):
    def __init__(self, code, message, index=None, feature=None, detail=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.index, self.feature, self.detail = index, feature, detail or {}


# --- small vector helpers (plain tuples) -------------------------------------------------

def add(a, b):
    return tuple(x + y for x, y in zip(a, b, strict=True))


def mul(a, k):
    return tuple(x * k for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def turn(vector, degrees, axis):
    """``vector`` turned ``degrees`` about the unit ``axis`` (right-hand rule)."""
    if not degrees:
        return tuple(vector)
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    k = dot(axis, vector)
    across = cross(axis, vector)
    return tuple(
        vector[i] * c + across[i] * s + axis[i] * k * (1 - c) for i in range(3)
    )


def box_of(shape):
    box = shape.bounding_box()
    return (box.min.X, box.min.Y, box.min.Z), (box.max.X, box.max.Y, box.max.Z)


def corners(low, high):
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1])
            for z in (low[2], high[2])]


def polar_step(count, angle):
    if angle >= 360:
        return 360.0 / count
    return angle / (count - 1) if count > 1 else 0.0


# --- solids -------------------------------------------------------------------------------

def primitive(spec):
    """The solid centred on its bounding box at the origin, before scale and rotation."""
    op = spec["op"]
    if op == "box":
        sx, sy, sz = spec["size"]
        kx, ky, kz = spec.get("scale", (1, 1, 1))
        return b3d.Box(sx * kx, sy * ky, sz * kz), True
    if op == "cylinder":
        return b3d.Cylinder(spec["diameter"] / 2, spec["height"]), False
    if op == "sphere":
        return b3d.Sphere(spec["diameter"] / 2), False
    w, d, h = spec["size"]
    t = spec["thickness"]
    if op == "l_bracket":
        # Base on the bottom, upright along the front (-Y) edge.
        part = b3d.Pos(w / 2, d / 2, t / 2) * b3d.Box(w, d, t) + b3d.Pos(
            w / 2, t / 2, h / 2
        ) * b3d.Box(w, t, h)
    else:
        # Four walls and a floor of one thickness, open at the top.
        part = b3d.Pos(w / 2, d / 2, h / 2) * b3d.Box(w, d, h) - b3d.Pos(
            w / 2, d / 2, t + (h - t + M) / 2
        ) * b3d.Box(w - 2 * t, d - 2 * t, h - t + M)
    return b3d.Pos(-w / 2, -d / 2, -h / 2) * part, False


def solid(spec):
    """A placed solid: scale (own axes, about the centre), rotate X, Y, Z (world), move."""
    part, scaled = primitive(spec)
    factors = tuple(spec.get("scale", (1, 1, 1)))
    if not scaled and factors != (1, 1, 1):
        part = b3d.scale(part, by=factors)
    rx, ry, rz = spec.get("rotate", (0, 0, 0))
    if rx or ry or rz:
        part = b3d.Rot(Z=rz) * b3d.Rot(Y=ry) * b3d.Rot(X=rx) * part
    return b3d.Pos(*spec.get("at", (0, 0, 0))) * part


def as_part(shape):
    if isinstance(shape, b3d.Part):
        return shape
    return b3d.Part(shape.wrapped) if getattr(shape, "wrapped", None) is not None else shape


# --- face frames ---------------------------------------------------------------------------

class Frame:
    """One face of a body's bounding box: its lowest corner, axes and size in mm."""

    def __init__(self, shape, face):
        low, high = box_of(shape)
        self.face = face
        self.n, self.u, self.v = FACES[face]
        self.corner = tuple(
            high[i] if self.n[i] > 0 else low[i] for i in range(3)
        )
        size = tuple(high[i] - low[i] for i in range(3))
        self.width = abs(dot(size, self.u))
        self.height = abs(dot(size, self.v))
        up = TEXT_UP.get(face, (0, 0, 1))
        self.read = cross(up, self.n)

    def point(self, uv):
        return add(self.corner, add(mul(self.u, uv[0]), mul(self.v, uv[1])))


def depth_behind(shape, origin, normal):
    """How far the body reaches behind the plane through ``origin`` along ``-normal``."""
    low, high = box_of(shape)
    return max(0.0, max(dot(add(origin, mul(c, -1)), normal) for c in corners(low, high)))


def prism(sketch, origin, x_dir, normal, start, length, inward=True):
    """``sketch`` on a plane facing ``normal``, ``start`` mm outside the face, then extruded
    ``length`` mm into the body (or out of it when ``inward`` is False)."""
    sign = 1 if inward else -1
    plane = b3d.Plane(origin=add(origin, mul(normal, sign * start)), x_dir=x_dir, z_dir=normal)
    return b3d.extrude(plane * sketch, amount=length, dir=mul(normal, -sign))


def reach(shape, origin, normal, depth):
    if depth == "through":
        return depth_behind(shape, origin, normal) + 2 * M
    return float(depth) + M


# --- the builder --------------------------------------------------------------------------

class Build:
    def __init__(self, tree):
        self.features = tree["features"]
        self.bodies = {}  # feature index -> current shape of a live solid
        self.where = {}  # id -> feature index
        self.applied = {}  # feature index -> how a face feature was placed
        self.warnings = []

    def fail(self, index, code, message, **detail):
        feature = self.features[index]
        raise KernelError(code, message, index, feature.get("id"), detail)

    def body(self, ref):
        return self.where[ref]

    def run(self):
        for index, feature in enumerate(self.features):
            if feature.get("id"):
                self.where[feature["id"]] = index
            target = None if feature["op"] in SOLID_OPS else self.target_of(feature)
            before = self.bodies[target].volume if target is not None else None
            try:
                self.step(index, feature)
            except KernelError:
                raise
            except Exception as exc:
                self.fail(index, "kernel_failed", short(exc))
            if target is not None:
                shape = self.bodies[target]
                if not shape.is_valid:
                    self.fail(index, "kernel_failed", "the result isn't a valid solid")
                if shape.volume <= 1e-9:
                    self.fail(index, "empty_result", "nothing of the body is left")
                if feature["op"] in CHANGES and abs(shape.volume - before) <= 1e-7 * before:
                    # A cut that misses the body, or a copy that lands inside it.
                    self.warnings.append(
                        {"code": "no_effect", "index": index, "feature": feature.get("id")}
                    )
        return [self.bodies[index] for index in sorted(self.bodies)]

    def target_of(self, feature):
        if feature["op"] == "pattern":
            source = self.features[self.where[feature["of"]]]
            if source["op"] in SOLID_OPS:
                return self.where[feature["of"]]
            return self.where[source["target"]]
        return self.where.get(feature.get("target"))

    def step(self, index, feature):
        op = feature["op"]
        if op in SOLID_OPS:
            self.bodies[index] = solid(feature)
            return
        if op == "pattern":
            self.pattern(index, feature)
            return
        target = self.body(feature["target"])
        shape = self.bodies[target]
        if op in FACE_OPS:
            frame = Frame(shape, feature.get("face", "top"))
            at = feature.get("at")
            if at is None:
                at = (frame.width / 2, frame.height / 2)
            self.applied[index] = (frame, tuple(at))
            self.bodies[target] = self.face_feature(feature, shape, frame, at, 0.0)
        elif op in ("cut", "union"):
            if feature.get("tool") is not None:
                other = solid(feature["tool"])
                self.bodies[target] = shape - other if op == "cut" else shape + other
            else:
                for ref in feature["bodies"]:
                    other = self.bodies.pop(self.body(ref))
                    shape = shape - other if op == "cut" else shape + other
                self.bodies[target] = shape
        elif op in ("fillet", "chamfer"):
            self.bodies[target] = self.round(index, feature, shape)
        elif op == "shell":
            self.bodies[target] = self.shell(index, feature, shape)
        elif op == "mirror":
            plane = {"XY": b3d.Plane.XY, "YZ": b3d.Plane.YZ, "XZ": b3d.Plane.XZ}[feature["plane"]]
            self.bodies[target] = shape + b3d.mirror(shape, about=plane)
        else:
            self.fail(index, "unsupported", f"the {op} op isn't supported")
        self.bodies[target] = as_part(self.bodies[target])

    # --- holes, slots, text ---------------------------------------------------------------

    def face_feature(self, feature, shape, frame, at, extra):
        op, n = feature["op"], frame.n
        origin = frame.point(at)
        if op == "hole":
            length = reach(shape, origin, n, feature.get("depth", "through"))
            tool = prism(b3d.Circle(feature["diameter"] / 2), origin, frame.u, n, M, length)
            if feature.get("cb_diameter") is not None:
                tool = tool + prism(
                    b3d.Circle(feature["cb_diameter"] / 2), origin, frame.u, n, M,
                    feature["cb_depth"] + M,
                )
            return shape - tool
        if op == "slot":
            length = reach(shape, origin, n, feature.get("depth", "through"))
            x_dir = turn(frame.u, feature.get("angle", 0) + extra, n)
            sketch = b3d.SlotOverall(feature["length"], feature["width"])
            return shape - prism(sketch, origin, x_dir, n, M, length)
        x_dir = turn(frame.read, extra, n)
        sketch = b3d.Text(feature["text"], font_size=feature["size"])
        if feature.get("mode", "engrave") == "engrave":
            return shape - prism(sketch, origin, x_dir, n, M, feature["depth"] + M)
        raised = prism(sketch, origin, x_dir, n, EMBED, feature["depth"] + EMBED, inward=False)
        return shape + raised

    # --- fillet and chamfer ---------------------------------------------------------------

    def edges(self, shape, which):
        low, high = box_of(shape)
        span = max(h - lo for lo, h in zip(low, high, strict=True))
        tol = max(1e-4, span * 1e-6)
        edges = shape.edges()
        if which == "all":
            return edges
        if which == "vertical":
            picked = []
            for edge in edges.filter_by(b3d.Axis.Z):
                mid = edge.position_at(0.5)
                on_x = abs(mid.X - low[0]) < tol or abs(mid.X - high[0]) < tol
                on_y = abs(mid.Y - low[1]) < tol or abs(mid.Y - high[1]) < tol
                if on_x and on_y:
                    picked.append(edge)
            return b3d.ShapeList(picked)
        level = high[2] if which == "top" else low[2]
        picked = []
        for edge in edges:
            box = edge.bounding_box()
            if abs(box.min.Z - level) < tol and abs(box.max.Z - level) < tol:
                picked.append(edge)
        return b3d.ShapeList(picked)

    def round(self, index, feature, shape):
        op, which = feature["op"], feature.get("edges", "all")
        size = feature["radius"] if op == "fillet" else feature["distance"]
        edges = self.edges(shape, which)
        if not edges:
            self.fail(index, "no_edges", f"there are no {which} edges to {op}", edges=which)
        try:
            if op == "fillet":
                result = b3d.fillet(edges, size)
            else:
                result = b3d.chamfer(edges, size)
            if result.is_valid and result.volume > 1e-9:
                return result
        except Exception:
            pass  # OpenCascade refused it; the failure below says why
        self.fail(
            index, "kernel_failed", f"the {op} doesn't fit", op=op, size=size, edges=which,
            room=round(room(shape, edges), 3),
        )

    def shell(self, index, feature, shape):
        face = feature.get("open", "top")
        n = FACES[face][0]
        axis = next(i for i in range(3) if n[i])
        low, high = box_of(shape)
        level = high[axis] if n[axis] > 0 else low[axis]
        span = max(h - lo for lo, h in zip(low, high, strict=True))
        tol = max(1e-4, span * 1e-6)
        openings = []
        for candidate in shape.faces():
            box = candidate.bounding_box()
            lo = (box.min.X, box.min.Y, box.min.Z)[axis]
            hi = (box.max.X, box.max.Y, box.max.Z)[axis]
            if abs(lo - level) < tol and abs(hi - level) < tol:
                openings.append(candidate)
        if not openings:
            axis_name = (b3d.Axis.X, b3d.Axis.Y, b3d.Axis.Z)[axis]
            ordered = shape.faces().sort_by(axis_name)
            openings = [ordered[-1] if n[axis] > 0 else ordered[0]]
        try:
            result = b3d.offset(shape, amount=-feature["thickness"], openings=openings)
            # OpenCascade can hand the solid back untouched (for example next to chamfers).
            if result.is_valid and 1e-9 < result.volume < shape.volume * (1 - 1e-6):
                return result
        except Exception:
            pass  # OpenCascade refused it; the failure below says why
        self.fail(
            index, "kernel_failed", "the shell doesn't fit", op="shell",
            size=feature["thickness"], thinnest=round(min(high[i] - low[i] for i in range(3)), 3),
        )

    # --- patterns -------------------------------------------------------------------------

    def offsets(self, feature):
        """(du, dv, turn) for each new instance; the original is never repeated."""
        if feature["kind"] == "linear":
            (nx, ny), (dx, dy) = feature["count"], feature["spacing"]
            return [(i * dx, j * dy, 0.0) for j in range(ny) for i in range(nx) if i or j]
        count, radius = feature["count"], feature["radius"]
        step = polar_step(count, feature.get("angle") or 360)
        return [(None, None, k * step) for k in range(count)] if radius is not None else []

    def pattern(self, index, feature):
        source_index = self.where[feature["of"]]
        source = self.features[source_index]
        offsets = self.offsets(feature)
        polar = feature["kind"] == "polar"
        radius = feature.get("radius") or 0.0
        if source["op"] in FACE_OPS:
            target = self.body(source["target"])
            frame, at = self.applied[source_index]
            for du, dv, angle in offsets:
                if polar:
                    spot = turn(mul(frame.u, radius), angle, frame.n)
                    du, dv = dot(spot, frame.u), dot(spot, frame.v)
                shape = self.bodies[target]
                self.bodies[target] = as_part(self.face_feature(
                    source, shape, frame, (at[0] + du, at[1] + dv), angle
                ))
            return
        if source["op"] in SOLID_OPS:
            target, original, centre = source_index, self.bodies[source_index], source["at"]
        else:  # a cut with a tool shape
            target, original, centre = (
                self.body(source["target"]), solid(source["tool"]), source["tool"]["at"],
            )
        copies = []
        for du, dv, angle in offsets:
            if polar:
                move = (
                    b3d.Pos(*centre) * b3d.Rot(Z=angle) * b3d.Pos(radius, 0, 0)
                    * b3d.Pos(*mul(centre, -1))
                )
            else:
                move = b3d.Pos(du, dv, 0)
            copies.append(move * original)
        shape = self.bodies[target]
        for copy in copies:
            shape = shape + copy if source["op"] in SOLID_OPS else shape - copy
        self.bodies[target] = as_part(shape)


def room(shape, edges):
    """The shortest edge of the faces next to ``edges``: what a fillet must fit within."""
    try:
        chosen = list(edges)
        lengths = []
        for face in shape.faces():
            face_edges = face.edges()
            if any(edge.is_same(other) for edge in chosen for other in face_edges):
                lengths.extend(other.length for other in face_edges)
        return min(lengths) if lengths else min(edge.length for edge in chosen)
    except Exception:
        return 0.0


def short(exc):
    text = " ".join(str(exc).split()) or type(exc).__name__
    return text[:300]


# --- commands -----------------------------------------------------------------------------

def facts(bodies):
    whole = b3d.Compound(bodies) if len(bodies) > 1 else bodies[0]
    low, high = box_of(whole)
    return {
        "volume": round(sum(body.volume for body in bodies), 4),
        "bbox": [round(high[i] - low[i], 4) for i in range(3)],
        "min": [round(value, 4) for value in low],
        "faces": sum(len(body.faces()) for body in bodies),
        "edges": sum(len(body.edges()) for body in bodies),
        "solids": sum(len(body.solids()) for body in bodies),
        "valid": all(body.is_valid for body in bodies),
    }, whole


def export(whole, formats, quality, folder):
    settings = QUALITY[quality]
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in formats:
        path = folder / f"model.{name}"
        path.unlink(missing_ok=True)
        if name == "glb":
            done = b3d.export_gltf(
                whole, str(path), unit=b3d.Unit.MM, binary=True,
                linear_deflection=settings["linear"], angular_deflection=settings["angular"],
            )
        elif name == "stl":
            done = b3d.export_stl(
                whole, str(path), tolerance=settings["linear"],
                angular_tolerance=settings["angular"],
            )
        else:
            done = b3d.export_step(whole, str(path))
        if done is False or not path.is_file() or path.stat().st_size == 0:
            raise KernelError("export_failed", f"the {name} file couldn't be written")
        files[name] = str(path.resolve())
    return files


def build(request):
    started = time.perf_counter()
    tree, quality = request.get("tree"), request.get("quality", "draft")
    formats = request.get("export") or ["glb"]
    folder = request.get("folder") or "build"
    if (
        not isinstance(tree, dict)
        or not isinstance(tree.get("features"), list)
        or not tree["features"]
        or quality not in QUALITY
        or not isinstance(formats, list)
        or any(name not in EXPORTS for name in formats)
        or not isinstance(folder, str)
        or not FOLDER.fullmatch(folder)
    ):
        raise KernelError("bad_request", "the build request isn't valid")
    builder = Build(tree)
    bodies = builder.run()
    if not bodies:
        raise KernelError("empty_result", "the design has no bodies left")
    result, whole = facts(bodies)
    files = export(whole, [name for name in EXPORTS if name in formats], quality,
                   Path.cwd() / folder)
    warnings = list(builder.warnings)
    if not result["valid"]:
        warnings.append({"code": "invalid_solid", "index": None, "feature": None})
    return {"ok": True, "facts": result, "files": files, "warnings": warnings,
            "seconds": round(time.perf_counter() - started, 3)}


def handle(request):
    command = request.get("cmd")
    if command == "ping":
        return {"ok": True, "version": b3d.__version__}
    if command == "build":
        try:
            return build(request)
        except KernelError as error:
            return {"ok": False, "code": error.code, "message": error.message,
                    "feature": error.feature, "index": error.index, "detail": error.detail}
    return {"ok": False, "code": "bad_request", "message": "unknown command"}


def main():
    global b3d
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        import build123d
    except Exception as exc:
        protocol.write(json.dumps({"id": None, "ok": False, "code": "kernel_missing",
                                   "message": short(exc)}) + "\n")
        protocol.flush()
        return 3
    b3d = build123d
    stream = sys.stdin.buffer
    while True:
        line = stream.readline(MAX_REQUEST + 1)
        if not line:
            return 0
        if len(line) > MAX_REQUEST:
            while line and not line.endswith(b"\n"):
                line = stream.readline(MAX_REQUEST + 1)
            reply = {"id": None, "ok": False, "code": "bad_request", "message": "too large"}
        else:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("not an object")
            except ValueError:
                reply = {"id": None, "ok": False, "code": "bad_request", "message": "not JSON"}
            else:
                if request.get("cmd") == "exit":
                    return 0
                try:
                    reply = handle(request)
                except Exception as exc:
                    reply = {"ok": False, "code": "kernel_failed", "message": short(exc),
                             "feature": None, "index": None, "detail": {}}
                reply["id"] = request.get("id")
        protocol.write(json.dumps(reply, allow_nan=False) + "\n")
        protocol.flush()


if __name__ == "__main__":
    sys.exit(main())
