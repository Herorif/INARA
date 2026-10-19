"""Fixed bundled Blender bridge. Only imports our newly generated embedded GLB."""

import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector

folder = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
with (folder / "model.json").open("rb") as stream:
    metadata = json.loads(stream.read(32769))
presentation = metadata.get("presentation", {})
camera_direction = {"isometric": (2.8, -3.5, 2.5), "top": (0, -0.001, 4), "front": (0, -4, 1)}[
    presentation.get("camera", "isometric")
]
lighting = {"soft": (700, 600), "studio": (1000, 500), "contrast": (1400, 200)}[
    presentation.get("lighting", "studio")
]
quality = presentation.get("quality", "preview")
if quality not in ("preview", "standard"):
    raise ValueError("Unsupported render quality")
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(folder / "model.glb"))
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
if not meshes or len(meshes) > 8:
    raise ValueError("Unexpected scene objects")
# Export meshes before adding the presentation camera/lights.
bpy.ops.export_scene.gltf(
    filepath=str(folder / "blender.glb"), export_format="GLB", export_animations=False
)
points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
low = Vector(tuple(min(point[i] for point in points) for i in range(3)))
high = Vector(tuple(max(point[i] for point in points) for i in range(3)))
center = (low + high) / 2
radius = max((high - low).length / 2, 0.001)
bpy.ops.object.camera_add(location=center + Vector(camera_direction) * radius)
camera = bpy.context.object
camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.type = "ORTHO"
camera.data.ortho_scale = radius * 2.7
scene = bpy.context.scene
scene.camera = camera
for direction, strength in [((2, -3, 4), lighting[0]), ((-3, 1, 2), lighting[1])]:
    bpy.ops.object.light_add(type="AREA", location=center + Vector(direction) * radius)
    light = bpy.context.object
    light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
    light.data.energy = strength * radius * radius
    light.data.shape = "DISK"
    light.data.size = radius * 3
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 8 if quality == "preview" else 16
scene.render.threads_mode = "FIXED"
scene.render.threads = 2
scene.render.resolution_x = 640 if quality == "preview" else 960
scene.render.resolution_y = 480 if quality == "preview" else 720
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(folder / "model.png")
scene.world.color = (
    (0.08, 0.08, 0.08) if presentation.get("background", "dark") == "dark" else (0.3, 0.3, 0.3)
)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(folder / "model.blend"))
bpy.ops.render.render(write_still=True)
