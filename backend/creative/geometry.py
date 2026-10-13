"""Bounded parametric solids and standalone STL/glTF exporters, using only stdlib."""

from collections import Counter
import itertools
import json
import math
import struct


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def normal(a, b, c):
    vector = cross(sub(b, a), sub(c, a))
    length = math.sqrt(sum(x * x for x in vector))
    if length <= 0:
        raise ValueError("Degenerate triangle")
    return tuple(x / length for x in vector)


def build(recipe):
    """Mesh exposed faces of a shared coordinate grid; internal faces disappear."""
    w, d, h, t = (recipe[key] for key in ("width", "depth", "height", "thickness"))
    shape = recipe["shape"]
    if shape == "box":
        planes = [[0, w], [0, d], [0, h]]
    elif shape == "bracket":
        planes = [[0, w], [0, t, d], [0, t, h]]
    elif shape == "enclosure":
        planes = [[0, t, w - t, w], [0, t, d - t, d], [0, t, h]]
    else:
        raise ValueError("Unknown shape")
    occupied = set()
    for cell in itertools.product(*(range(len(axis) - 1) for axis in planes)):
        x, y, z = cell
        if (
            shape == "box"
            or z == 0
            or (shape == "bracket" and y == 0)
            or (shape == "enclosure" and (x in (0, 2) or y in (0, 2)))
        ):
            occupied.add(cell)
    vertices, index, faces = [], {}, []
    for cell in sorted(occupied):
        for axis in range(3):
            # Remaining axes in cyclic order make a positive outward winding.
            u, v = (axis + 1) % 3, (axis + 2) % 3
            for sign in (-1, 1):
                neighbour = list(cell)
                neighbour[axis] += sign
                if tuple(neighbour) in occupied:
                    continue
                corners = []
                for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    point = list(cell)
                    point[axis] += sign == 1
                    point[u] += du
                    point[v] += dv
                    coordinate = tuple(planes[i][point[i]] for i in range(3))
                    if coordinate not in index:
                        index[coordinate] = len(vertices)
                        vertices.append(coordinate)
                    corners.append(index[coordinate])
                if sign == -1:
                    corners.reverse()
                faces.extend(
                    ((corners[0], corners[1], corners[2]), (corners[0], corners[2], corners[3]))
                )
    return vertices, faces


def validate(vertices, faces):
    if not vertices or not faces or len(faces) > 512:
        raise ValueError("Geometry limit exceeded")
    edges, directed = Counter(), Counter()
    volume = 0
    for face in faces:
        a, b, c = [vertices[i] for i in face]
        if not all(math.isfinite(x) for point in (a, b, c) for x in point):
            raise ValueError("Nonfinite coordinate")
        normal(a, b, c)
        volume += sum(a[i] * cross(b, c)[i] for i in range(3)) / 6
        for i, j in zip(face, (face[1], face[2], face[0])):
            edges[tuple(sorted((i, j)))] += 1
            directed[(i, j)] += 1
    if (
        any(count != 2 for count in edges.values())
        or any(directed[(j, i)] != count for (i, j), count in directed.items())
        or volume <= 0
    ):
        raise ValueError("Mesh is not a closed, consistently oriented solid")
    bounds = [
        [min(p[i] for p in vertices) for i in range(3)],
        [max(p[i] for p in vertices) for i in range(3)],
    ]
    return {
        "triangles": len(faces),
        "vertices": len(vertices),
        "watertight": True,
        "volume_mm3": volume,
        "bounds_mm": bounds,
    }


def stl(vertices, faces):
    data = bytearray(
        b"INARA parametric solid; units mm".ljust(80, b"\0") + struct.pack("<I", len(faces))
    )
    for face in faces:
        a, b, c = [vertices[i] for i in face]
        data.extend(struct.pack("<12fH", *normal(a, b, c), *a, *b, *c, 0))
    return bytes(data)


def glb(vertices, faces, name):
    # glTF uses metres and Y up; STL stays in CAD millimetres with Z up.
    positions, normals = [], []
    for face in faces:
        points = [vertices[i] for i in face]
        n = normal(*points)
        for x, y, z in points:
            positions.append((x / 1000, z / 1000, -y / 1000))
            normals.append((n[0], n[2], -n[1]))
    raw = b"".join(struct.pack("<3f", *p) for p in positions + normals)
    length = len(positions) * 12
    document = {
        "asset": {"version": "2.0", "generator": "INARA offline CAD"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "material": 0}]}],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.15, 0.75, 0.8, 1],
                    "metallicFactor": 0.25,
                    "roughnessFactor": 0.4,
                }
            }
        ],
        "buffers": [{"byteLength": len(raw)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": length, "target": 34962},
            {"buffer": 0, "byteOffset": length, "byteLength": length, "target": 34962},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": [min(p[i] for p in positions) for i in range(3)],
                "max": [max(p[i] for p in positions) for i in range(3)],
            },
            {"bufferView": 1, "componentType": 5126, "count": len(normals), "type": "VEC3"},
        ],
    }
    encoded = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    return (
        struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(encoded) + 8 + len(raw))
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(raw), 0x004E4942)
        + raw
    )
