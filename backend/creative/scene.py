"""Typed assembly geometry. Transforms are scale, then X/Y/Z rotation, then translation."""

import json
import math
import struct
from creative.geometry import build, validate, stl, glb

MATERIALS = {
    "cyan": ([0.15, 0.75, 0.8, 1], 0.25, 0.4),
    "titanium": ([0.42, 0.48, 0.56, 1], 0.85, 0.3),
    "amber": ([1.0, 0.4, 0.06, 1], 0.35, 0.35),
    "ceramic": ([0.88, 0.92, 0.96, 1], 0.0, 0.65),
}


def transform(point, obj):
    x, y, z = (point[i] * obj["scale"][i] for i in range(3))
    for axis, angle in enumerate(obj["rotation"]):
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        if axis == 0:
            y, z = c * y - s * z, s * y + c * z
        elif axis == 1:
            x, z = c * x + s * z, -s * x + c * z
        else:
            x, y = c * x - s * y, s * x + c * y
    return tuple(v + offset for v, offset in zip((x, y, z), obj["position"]))


def assemble(recipe):
    if recipe["shape"] != "scene":
        vertices, faces = build(recipe)
        return validate(vertices, faces), stl(vertices, faces), glb(vertices, faces, recipe["name"])
    vertices, faces, raw = [], [], bytearray()
    document = {
        "asset": {"version": "2.0", "generator": "INARA scene assembly"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "materials": [],
        "buffers": [],
        "bufferViews": [],
        "accessors": [],
    }
    for obj in recipe["objects"]:
        local, triangles = build(obj)
        local = [transform(point, obj) for point in local]
        validate(local, triangles)
        offset = len(vertices)
        vertices.extend(local)
        faces.extend(tuple(i + offset for i in face) for face in triangles)
        binary = glb(local, triangles, obj["name"])
        length = struct.unpack_from("<I", binary, 12)[0]
        part = json.loads(binary[20 : 20 + length])
        data = binary[28 + length :]
        mesh_index, view_index, accessor_index = (
            len(document["meshes"]),
            len(document["bufferViews"]),
            len(document["accessors"]),
        )
        for view in part["bufferViews"]:
            view["byteOffset"] += len(raw)
            document["bufferViews"].append(view)
        for accessor in part["accessors"]:
            accessor["bufferView"] += view_index
            document["accessors"].append(accessor)
        primitive = part["meshes"][0]["primitives"][0]
        primitive["attributes"] = {
            key: value + accessor_index for key, value in primitive["attributes"].items()
        }
        primitive["material"] = mesh_index
        document["meshes"].append(part["meshes"][0])
        document["nodes"].append({"name": obj["name"], "mesh": mesh_index})
        document["scenes"][0]["nodes"].append(mesh_index)
        color, metal, rough = MATERIALS[obj["material"]]
        document["materials"].append(
            {
                "name": obj["material"],
                "pbrMetallicRoughness": {
                    "baseColorFactor": color,
                    "metallicFactor": metal,
                    "roughnessFactor": rough,
                },
            }
        )
        raw.extend(data)
    stats = validate(vertices, faces, max_faces=4096)
    document["buffers"] = [{"byteLength": len(raw)}]
    encoded = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    payload = (
        struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(raw))
        + struct.pack("<II", len(encoded), 0x4E4F534A)
        + encoded
        + struct.pack("<II", len(raw), 0x004E4942)
        + raw
    )
    return stats, stl(vertices, faces), payload
