"""scripts/build-icons.py: PNG and ICO encoding, pixel frames, badges, Android resources,
the review manifest and where the tool writes.

Every build runs in a temporary root with stand-in renders, so no Blender is needed and
nothing touches the repository's own .runtime/.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import zlib

import pytest

spec = importlib.util.spec_from_file_location(
    "build_icons", Path(__file__).resolve().parents[1] / "scripts/build-icons.py"
)
bi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bi)

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
J16 = {(9, y) for y in range(3, 11)} | {(10, y) for y in range(3, 11)} \
    | {(x, 11) for x in range(6, 10)} | {(6, 10), (5, 9), (5, 10)}
J16_LIGHT = {(9, y) for y in range(3, 11)}


def decode_png(data):
    """Minimal 8-bit RGBA decoder (all five filter types) -> (width, height, rows)."""
    assert data[:8] == bi.PNG_SIGNATURE
    offset, idat = 8, b""
    while offset < len(data):
        length, kind = struct.unpack_from(">I4s", data, offset)
        body = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            assert (depth, colour) == (8, 6)
        elif kind == b"IDAT":
            idat += body
        offset += 12 + length
    raw = zlib.decompress(idat)
    stride, rows, prev, pos = width * 4, [], bytearray(width * 4), 0
    for _ in range(height):
        kind, line = raw[pos], bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            a = line[i - 4] if i >= 4 else 0
            b, c = prev[i], prev[i - 4] if i >= 4 else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, rows


def pixel(rows, x, y):
    return tuple(rows[y][4 * x:4 * x + 4])


def opaque(code):
    return (*bi.rgb(code), 255)


def ico_entries(data):
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1)
    entries = []
    for i in range(count):
        w, h, colours, res, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * i)
        entries.append({"w": w or 256, "h": h or 256, "colours": colours, "reserved": res,
                        "planes": planes, "bits": bits, "length": length, "offset": offset,
                        "png": data[offset:offset + length]})
    return entries


def ico_frame(path, size):
    for entry in ico_entries(Path(path).read_bytes()):
        if entry["w"] == size:
            return decode_png(entry["png"])
    raise AssertionError(f"no {size} frame in {path}")


# --- fixture: a temporary repository root with stand-in renders ---------------------------
def fake_root(tmp_path):
    scene = tmp_path / "art" / "blender" / "jarvis-emblem.py"
    scene.parent.mkdir(parents=True)
    scene.write_text("# stand-in scene\n")
    review = tmp_path / ".runtime" / "blender" / "review"
    review.mkdir(parents=True)
    outputs = {}
    for name in bi.required_renders():
        size = bi.render_size(name)
        data = bi.encode_png(size, size, bytes((10, 16, 23, 255)) * (size * size))
        (review / name).write_bytes(data)
        outputs[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {"format": 1, "scene": "jarvis-emblem", "generator": "art/blender/jarvis-emblem.py",
                "generator_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
                "blender_version": "5.2.3", "scene_args": [], "outputs": outputs}
    (review / "jarvis-emblem.manifest.json").write_text(json.dumps(manifest))
    return tmp_path


@pytest.fixture
def built(tmp_path):
    root = fake_root(tmp_path)
    manifest = bi.build(root)
    return root, root / ".runtime" / "icons" / "review", manifest


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# --- PNG encoder ---------------------------------------------------------------------------
def test_png_encoder_signature_chunks_crc_and_idat_size():
    rgba = bytes(range(256)) * 3     # 768 bytes: 16 x 12 RGBA pixels
    data = bi.encode_png(16, 12, rgba)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset, kinds = 8, []
    while offset < len(data):
        length, kind = struct.unpack_from(">I4s", data, offset)
        body = data[offset + 4:offset + 8 + length]
        (crc,) = struct.unpack_from(">I", data, offset + 8 + length)
        assert zlib.crc32(body) & 0xFFFFFFFF == crc
        if kind == b"IHDR":
            assert struct.unpack(">IIBBBBB", body[4:]) == (16, 12, 8, 6, 0, 0, 0)
        if kind == b"IDAT":
            raw = zlib.decompress(body[4:])
            assert len(raw) == 12 * (1 + 16 * 4)
        kinds.append(kind)
        offset += 12 + length
    assert kinds == [b"IHDR", b"IDAT", b"IEND"] and offset == len(data)
    width, height, rows = decode_png(data)
    assert (width, height) == (16, 12) and b"".join(rows) == rgba


def test_png_encoder_is_deterministic_and_checks_the_buffer():
    rgba = bytes(4 * 9)
    assert bi.encode_png(3, 3, rgba) == bi.encode_png(3, 3, rgba)
    with pytest.raises(bi.IconError):
        bi.encode_png(3, 3, rgba[:-1])


def test_png_info_rejects_a_bad_crc_and_trailing_data():
    data = bytearray(bi.encode_png(2, 2, bytes(16)))
    assert bi.png_info(bytes(data)) == (2, 2, 8, 6)
    with pytest.raises(bi.IconError):
        bi.png_info(bytes(data) + b"x")
    data[20] ^= 1   # inside IHDR
    with pytest.raises(bi.IconError, match="CRC"):
        bi.png_info(bytes(data))


# --- ICO -----------------------------------------------------------------------------------
def check_ico(path, sizes):
    data = Path(path).read_bytes()
    entries = ico_entries(data)
    assert [e["w"] for e in entries] == list(sizes)
    offset = 6 + 16 * len(entries)
    for entry, size in zip(entries, sizes, strict=True):
        assert entry["h"] == entry["w"] == size
        assert (entry["colours"], entry["reserved"], entry["planes"], entry["bits"]) == (0, 0, 1, 32)
        assert entry["offset"] == offset
        assert entry["png"][:8] == bi.PNG_SIGNATURE
        assert bi.png_info(entry["png"]) == (size, size, 8, 6)
        offset += entry["length"]
    assert offset == len(data)
    return entries


def test_app_ico_has_every_frame_as_png_with_correct_offsets(built):
    _root, out, _manifest = built
    entries = check_ico(out / "jarvis.ico", (16, 20, 24, 32, 40, 48, 64, 96, 128, 256))
    raw = (out / "jarvis.ico").read_bytes()
    assert raw[6 + 16 * 9] == 0 and raw[6 + 16 * 9 + 1] == 0      # 256 is stored as 0
    renders = out.parents[1] / "blender" / "review"
    for entry in entries:
        if entry["w"] >= 32:     # 32 and up are the reviewed renders, byte for byte
            assert entry["png"] == (renders / f"emblem-{entry['w']}.png").read_bytes()
        else:                    # 16, 20, 24 are the ready pixel frames
            assert entry["png"] == ico_entries(
                (out / "tray" / "jarvis-ready.ico").read_bytes())[(16, 20, 24).index(entry["w"])]["png"]


def test_tray_icos_have_the_four_pixel_frames(built):
    _root, out, _manifest = built
    for state in bi.STATES:
        check_ico(out / "tray" / f"jarvis-{state}.ico", (16, 20, 24, 32))


def test_ico_refuses_a_frame_of_the_wrong_size():
    with pytest.raises(bi.IconError):
        bi.encode_ico([(16, bi.encode_png(8, 8, bytes(256)))])


# --- pixel frames --------------------------------------------------------------------------
@pytest.mark.parametrize("state", list(bi.STATES))
def test_16px_j_has_exactly_the_designed_pixels_and_colours(built, state):
    _root, out, _manifest = built
    _w, _h, rows = ico_frame(out / "tray" / f"jarvis-{state}.ico", 16)
    light, rest = opaque(bi.STATES[state]["light"]), opaque(bi.STATES[state]["rest"])
    for y in range(16):
        for x in range(16):
            value = pixel(rows, x, y)
            if (x, y) in J16_LIGHT:
                assert value == light, (x, y)
            elif (x, y) in J16:
                assert value == rest, (x, y)
            else:
                assert value not in (light, rest), (x, y)


def test_state_colours_match_the_design():
    expected = {
        "ready": ("#2A8A96", "#B0EFF5", "#70E0ED", None),
        "talking": ("#70E0ED", "#EFFCFD", "#B0EFF5", None),
        "paused": ("#3A4A5C", "#9FB0BF", "#74849A", None),
        "calls": ("#2A8A96", "#B0EFF5", "#70E0ED", "#6DE2B5"),
        "attention": ("#2A8A96", "#B0EFF5", "#70E0ED", "#FFC670"),
    }
    for state, (ring, light, rest, badge) in expected.items():
        spec = bi.STATES[state]
        assert (spec["ring"], spec["light"], spec["rest"], spec["badge"]) == (ring, light, rest, badge)
    assert bi.STATES["talking"]["ring_w"] == pytest.approx(1.4 / 16)


@pytest.mark.parametrize("size,stem", [(16, 2), (20, 2), (24, 3), (32, 4)])
def test_larger_j_frames_keep_the_design_rules(size, stem):
    cells = bi.j_cells(size)
    xs, ys = [x for x, _y, _c in cells], [y for _x, y, _c in cells]
    top = min(ys)
    stem_cols = sorted(x for x, y, _c in cells if y == top)
    assert len(stem_cols) == stem and stem_cols == list(range(stem_cols[0], stem_cols[0] + stem))
    assert stem_cols[-1] == max(xs)                         # the stem is the right edge
    light = sorted({x for x, _y, c in cells if c == "L"})
    assert light == stem_cols[:max(1, stem // 2)]          # left column(s) of the stem
    height = max(ys) - top + 1
    assert 0.53 <= height / size <= 0.57
    assert (min(xs) + max(xs) + 1) / 2 == size / 2          # centred horizontally
    assert abs((top + max(ys) + 1) / 2 - size / 2) <= 0.5   # and vertically
    if size > 16:                                           # the hook is as thick as the stem
        bottom = [y for x, y, _c in cells if x == (min(xs) + max(xs)) // 2 and y > top + 1]
        assert len(bottom) == stem


def test_frame_corners_are_transparent_and_the_disc_is_antialiased(built):
    _root, out, _manifest = built
    _w, _h, rows = ico_frame(out / "tray" / "jarvis-ready.ico", 16)
    assert pixel(rows, 0, 0)[3] == 0
    assert pixel(rows, 8, 8)[3] == 255
    edge_alphas = {pixel(rows, x, 0)[3] for x in range(16)}
    assert any(0 < a < 255 for a in edge_alphas)


# --- badges --------------------------------------------------------------------------------
@pytest.mark.parametrize("size", bi.TRAY_SIZES)
def test_badges_sit_inside_the_frame_and_clear_the_j(built, size):
    _root, out, _manifest = built
    cx, cy, r, _outline = bi.badge(size)
    assert r <= cx <= size - r and r <= cy <= size - r
    bi.check_badge(size)
    j = {(x, y): c for x, y, c in bi.j_cells(size)}
    for state in ("calls", "attention"):
        _w, _h, rows = ico_frame(out / "tray" / f"jarvis-{state}.ico", size)
        spec = bi.STATES[state]
        colour = opaque(spec["badge"])
        dot = {(x, y) for y in range(size) for x in range(size) if pixel(rows, x, y) == colour}
        assert dot, f"{state} {size}: no solid badge pixels"
        assert not dot & set(j)
        for x, y in dot:   # solid dot pixels lie inside the badge circle
            assert (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r
        for (x, y), cell in j.items():   # the J stays exact under the badge
            assert pixel(rows, x, y) == opaque(spec["light"] if cell == "L" else spec["rest"])


def test_16px_badge_matches_the_design():
    assert bi.badge(16) == (13.0, 13.0, pytest.approx(2.6), pytest.approx(1.0))


def test_check_badge_refuses_a_badge_on_the_j(monkeypatch):
    monkeypatch.setitem(bi.BADGE_CENTRE, 16, (11.0, 11.0))
    with pytest.raises(bi.IconError, match="touches the J"):
        bi.check_badge(16)


# --- Android -------------------------------------------------------------------------------
def test_android_adaptive_icon_xml(built):
    _root, out, _manifest = built
    res = out / "android" / "res"
    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        root = ET.parse(res / "mipmap-anydpi-v26" / name).getroot()
        assert root.tag == "adaptive-icon"
        drawables = {child.tag: child.attrib[f"{ANDROID_NS}drawable"] for child in root}
        assert drawables == {"background": "@color/ic_launcher_background",
                             "foreground": "@mipmap/ic_launcher_foreground",
                             "monochrome": "@mipmap/ic_launcher_monochrome"}
    colours = ET.parse(res / "values" / "ic_launcher_background.xml").getroot()
    assert [(c.tag, c.attrib["name"], c.text) for c in colours] == [
        ("color", "ic_launcher_background", "#05080C")]


def test_android_mipmaps_are_the_reviewed_renders(built):
    root, out, _manifest = built
    renders = root / ".runtime" / "blender" / "review"
    for density, size in bi.ANDROID_DENSITIES:
        folder = out / "android" / "res" / f"mipmap-{density}"
        for layer in ("foreground", "monochrome"):
            data = (folder / f"ic_launcher_{layer}.png").read_bytes()
            assert data == (renders / f"android-{layer}-{size}.png").read_bytes()
            assert bi.png_info(data)[:2] == (size, size)
    assert not list((out / "android" / "res").glob("mipmap-*/ic_launcher.png"))


# --- manifest, outputs and determinism ----------------------------------------------------
def test_manifest_lists_every_output_with_its_hash(built):
    _root, out, manifest = built
    on_disk = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert on_disk == set(manifest["outputs"]) | {"manifest.json"}
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == manifest
    for name, record in manifest["outputs"].items():
        data = (out / name).read_bytes()
        assert record["sha256"] == hashlib.sha256(data).hexdigest()
        assert record["bytes"] == len(data)
    assert manifest["outputs"]["jarvis.ico"]["frames"] == list(bi.ICO_SIZES)
    expected = {"jarvis.ico", "jarvis.png", "setup/emblem-64.png", "setup/emblem-128.png"} \
        | {f"tray/jarvis-{s}.ico" for s in ("ready", "talking", "paused", "calls", "attention")} \
        | {f"ui/mark-{size}.png" for size in (24, 32, 48, 64, 96)}
    assert expected <= set(manifest["outputs"])
    assert not {"jarvis-mark-20.png", "jarvis-mark-40.png"} & set(manifest["outputs"])


def test_ui_marks_are_the_ready_frame_and_the_reviewed_renders(built):
    root, out, manifest = built
    renders = root / ".runtime" / "blender" / "review"
    ready = {e["w"]: e["png"] for e in ico_entries((out / "tray" / "jarvis-ready.ico").read_bytes())}
    assert (out / "ui" / "mark-24.png").read_bytes() == ready[24]
    for size in (32, 48, 64, 96):
        assert (out / "ui" / f"mark-{size}.png").read_bytes() \
            == (renders / f"emblem-{size}.png").read_bytes()
    for size in bi.UI_MARKS:
        assert manifest["outputs"][f"ui/mark-{size}.png"]["pixels"] == [size, size]


def test_builds_are_byte_identical_and_empty_the_folder_first(tmp_path):
    root = fake_root(tmp_path)
    bi.build(root)
    out = root / ".runtime" / "icons" / "review"
    first = snapshot(out)
    (out / "stale.png").write_bytes(b"old")
    bi.build(root)
    assert snapshot(out) == first


def test_nothing_is_written_outside_the_icon_review_folder(tmp_path):
    root = fake_root(tmp_path)
    before = snapshot(root)
    bi.build(root)
    after = snapshot(root)
    changed = {name for name in after if before.get(name) != after[name]}
    assert changed and all(name.startswith(".runtime/icons/review/") for name in changed)
    assert set(before) <= set(after)


def test_refuses_renders_from_an_older_scene_script(tmp_path):
    root = fake_root(tmp_path)
    (root / "art" / "blender" / "jarvis-emblem.py").write_text("# edited\n")
    with pytest.raises(bi.IconError, match="changed since the renders"):
        bi.build(root)
    assert not (root / ".runtime" / "icons").exists()


def test_refuses_a_render_that_changed_since_review(tmp_path):
    root = fake_root(tmp_path)
    path = root / ".runtime" / "blender" / "review" / "emblem-48.png"
    path.write_bytes(bi.encode_png(48, 48, bytes(4 * 48 * 48)))
    with pytest.raises(bi.IconError, match="changed since review"):
        bi.build(root)


def test_refuses_a_missing_manifest(tmp_path):
    assert bi.main([], root=tmp_path) == 1
    assert not (tmp_path / ".runtime" / "icons").exists()


# --- publish -------------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]
APPROVALS = json.loads((REPO / "art" / "icons" / "publish.json").read_text(encoding="utf-8"))


def approve(root, outputs=None):
    path = root / "art" / "icons" / "publish.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    value = APPROVALS if outputs is None else {"format": 1, "outputs": outputs}
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def reviewed(tmp_path):
    root = fake_root(tmp_path)
    bi.build(root)
    approve(root)
    return root


def published(root):
    return {name: (root / target).read_bytes() for name, target in APPROVALS["outputs"].items()
            if (root / target).exists()}


def test_publish_copies_the_reviewed_bytes_to_every_approved_destination(reviewed, capsys):
    out = reviewed / ".runtime" / "icons" / "review"
    before = snapshot(out)
    entries = bi.publish(reviewed)
    for name, target in APPROVALS["outputs"].items():
        assert (reviewed / target).read_bytes() == (out / name).read_bytes(), name
    assert snapshot(out) == before        # no rebuild: the review folder is untouched
    printed = capsys.readouterr().out
    assert "Add to docs/ASSET_OWNERSHIP.json" in printed
    assert json.loads(printed.split("confirms:\n", 1)[1]) == entries


def test_publish_prints_ownership_entries_for_renderer_assets_only(reviewed):
    manifest = json.loads((reviewed / ".runtime/icons/review/manifest.json").read_text())
    entries = bi.publish(reviewed)
    renderer = sorted(t for t in APPROVALS["outputs"].values()
                      if t.startswith(("assets/", "public/", "src/")))
    assert sorted(e["path"] for e in entries) == renderer and len(renderer) == 12
    source = manifest["source"]
    origin = (f"owner-generated: scripts/build-icons.py (sha256 {manifest['generator_sha256']}) "
              f"from art/blender/jarvis-emblem.py (sha256 {source['generator_sha256']}), "
              "Blender 5.2.3")
    by_target = {t: n for n, t in APPROVALS["outputs"].items()}
    for entry in entries:
        assert entry == {"path": entry["path"],
                         "sha256": manifest["outputs"][by_target[entry["path"]]]["sha256"],
                         "origin": origin, "owner": None, "license_evidence": [],
                         "decision": "pending"}


def test_approved_destinations_are_the_agreed_set():
    targets = set(APPROVALS["outputs"].values())
    res = "android/app/src/main/res/"
    expected = {"assets/icons/jarvis.ico", "assets/icons/jarvis.png",
                "native/setup/emblem-128.png",
                res + "mipmap-anydpi-v26/ic_launcher.xml",
                res + "mipmap-anydpi-v26/ic_launcher_round.xml",
                res + "values/ic_launcher_background.xml"} \
        | {f"assets/icons/tray/jarvis-{s}.ico" for s in bi.STATES} \
        | {f"src/assets/icons/mark-{n}.png" for n in bi.UI_MARKS} \
        | {f"{res}mipmap-{d}/ic_launcher_{layer}.png" for d, _ in bi.ANDROID_DENSITIES
           for layer in ("foreground", "monochrome")}
    assert targets == expected and len(APPROVALS["outputs"]) == len(expected)


def refused(root, match):
    with pytest.raises(bi.IconError, match=match):
        bi.publish(root)
    assert published(root) == {}
    assert bi.main(["--publish"], root=root) == 1


def test_publish_refuses_without_approvals(tmp_path):
    root = fake_root(tmp_path)
    bi.build(root)
    refused(root, "nothing is approved")
    approve(root, {})
    refused(root, "not a format 1")


def test_publish_refuses_without_a_review(tmp_path):
    root = fake_root(tmp_path)
    approve(root)
    refused(root, "Nothing reviewed")


def test_publish_refuses_a_reviewed_file_whose_hash_changed(reviewed):
    (reviewed / ".runtime/icons/review/tray/jarvis-calls.ico").write_bytes(b"tampered")
    refused(reviewed, "changed since review")


def test_publish_refuses_a_missing_reviewed_file(reviewed):
    (reviewed / ".runtime/icons/review/ui/mark-48.png").unlink()
    refused(reviewed, "missing")


def test_publish_refuses_when_the_scene_script_changed(reviewed):
    (reviewed / "art/blender/jarvis-emblem.py").write_text("# edited after review\n")
    refused(reviewed, "jarvis-emblem.py changed since the review build")


def test_publish_refuses_when_build_icons_changed(reviewed, tmp_path, monkeypatch):
    edited = tmp_path / "build-icons-edited.py"
    edited.write_bytes(bi.GENERATOR.read_bytes() + b"\n# edited after review\n")
    monkeypatch.setattr(bi, "GENERATOR", edited)
    refused(reviewed, "build-icons.py changed since the review build")


@pytest.mark.parametrize("target", [
    "dist/jarvis.ico", "public/jarvis.ico", "backend/jarvis.ico", "android/app/jarvis.ico",
    "../outside/jarvis.ico", "assets/../backend/jarvis.ico", "assets/./jarvis.ico",
    "assets//jarvis.ico", "assets\\icons\\jarvis.ico", "C:/assets/jarvis.ico",
    "/assets/jarvis.ico", "src/app/jarvis.ico", "native/jarvis.ico", "", 7,
])
def test_publish_refuses_unapproved_destinations(reviewed, target):
    approve(reviewed, {"jarvis.ico": target})
    with pytest.raises(bi.IconError, match="Unsupported publish destination"):
        bi.publish(reviewed)
    assert not (reviewed / "assets").exists() and not (reviewed.parent / "outside").exists()


@pytest.mark.parametrize("output", ["../review/jarvis.ico", "manifest.json", "tray\\x.ico"])
def test_publish_refuses_unsafe_output_names(reviewed, output):
    approve(reviewed, {output: "assets/icons/jarvis.ico"})
    refused(reviewed, "Unsupported publish destination")


def junction(link, target):
    winapi = pytest.importorskip("_winapi")
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    winapi.CreateJunction(str(target), str(link))
    assert link.is_junction()


def test_publish_refuses_a_destination_through_a_junction(reviewed, tmp_path):
    outside = tmp_path / "outside"
    junction(reviewed / "assets" / "icons", outside)
    refused(reviewed, "goes through a link")
    assert not any(outside.iterdir())


def test_publish_refuses_a_symlinked_destination(reviewed, tmp_path):
    outside = tmp_path / "outside.ico"
    outside.write_bytes(b"not ours")
    link = reviewed / "assets" / "icons" / "jarvis.ico"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks need Developer Mode or elevation on this machine")
    with pytest.raises(bi.IconError, match="goes through a link"):
        bi.publish(reviewed)
    assert outside.read_bytes() == b"not ours"


def test_publish_refuses_a_linked_review_folder(reviewed, tmp_path):
    review = reviewed / ".runtime/icons/review"
    moved = tmp_path / "elsewhere"
    (review / "tray").rename(moved)
    junction(review / "tray", moved)
    refused(reviewed, "missing or linked")


def test_publish_refuses_linked_approvals(reviewed, tmp_path):
    elsewhere = tmp_path / "approvals"
    (reviewed / "art/icons").rename(elsewhere)
    junction(reviewed / "art/icons", elsewhere)
    refused(reviewed, "must not be a link")


def test_publish_checks_everything_before_copying_anything(reviewed):
    # ui/mark-96 is checked last (sorted); nothing may be copied before that refusal.
    (reviewed / ".runtime/icons/review/ui/mark-96.png").write_bytes(b"tampered")
    refused(reviewed, "changed since review")


# --- the published files are the approved bytes ------------------------------------------
# sha256 of each published output in the owner-approved review build (commit a75a43e).
# Publishing and every later review build must keep these bytes.
APPROVED = {
    "android/res/mipmap-anydpi-v26/ic_launcher.xml":
        "5bef67e3eba5c56f6ca0f96173c76e654977bce5ea91f0161fce94c5f52bbef7",
    "android/res/mipmap-anydpi-v26/ic_launcher_round.xml":
        "5bef67e3eba5c56f6ca0f96173c76e654977bce5ea91f0161fce94c5f52bbef7",
    "android/res/mipmap-hdpi/ic_launcher_foreground.png":
        "cd7b1d2d89eea2f269406a31774d1cca3ada116a91598fd1ab3b7cc0ec36edf8",
    "android/res/mipmap-hdpi/ic_launcher_monochrome.png":
        "804079ea1eed7e4117125159db9aa5c55efc00978a0000b6126e0e768846af7f",
    "android/res/mipmap-mdpi/ic_launcher_foreground.png":
        "e38c8379895db7d617f0ae474a5a9f5130a5bcc24b1e4b78a61bff0d54fceb5d",
    "android/res/mipmap-mdpi/ic_launcher_monochrome.png":
        "47fd376541c477d6b2f4e3503267e4f2062edf001a38f96dd62ac8730c9dfce4",
    "android/res/mipmap-xhdpi/ic_launcher_foreground.png":
        "794dc6d86df7878f669ccb4f602967b23c6b024f51e3df77aaf8db4beec35dc5",
    "android/res/mipmap-xhdpi/ic_launcher_monochrome.png":
        "81ad24274409d47ba8915d02ee03b11c9f98812d1eac9a30ad048bb6dba78be9",
    "android/res/mipmap-xxhdpi/ic_launcher_foreground.png":
        "ad2ba220c3d4b5fa1889b75da5133fd1938b744a36e02e0c87c850205954096c",
    "android/res/mipmap-xxhdpi/ic_launcher_monochrome.png":
        "3bd55eb30c7003590dc71850ee963945eda04f370b15dca0b046055ebc33e94f",
    "android/res/mipmap-xxxhdpi/ic_launcher_foreground.png":
        "7c14896a40309043171eebd518e17ca4b629233cca09bf033e5bb0d4f0c28e70",
    "android/res/mipmap-xxxhdpi/ic_launcher_monochrome.png":
        "2a7f45f995e62ebc46b77221f29dc3042a02b88b5cfbaa62102691f314f56da2",
    "android/res/values/ic_launcher_background.xml":
        "9e639b4aa15b683edefd02c889fdb45867eb937348395077aaf9a18fabb2f754",
    "jarvis.ico": "8741f827f2a59febd4293d508de2993e5664100d8981a0d4807ac2f4cf0e045b",
    "jarvis.png": "2bfde7ae0d4fb949b8b115f8579041acf807a94274746df1022ebe24d11f936e",
    "setup/emblem-128.png": "66ae0d8f600bb72df418b8a9bea37ddd01da8095e6f7b96cd8e497c593d46279",
    "tray/jarvis-attention.ico":
        "ed4bca70196ea67a7f3b025eb540f22ed7949797c098f74ad2eff6da306e6c60",
    "tray/jarvis-calls.ico": "0858c09aace254421648a75367ca3f433005e6abfa4b1291db8482ad70f685b8",
    "tray/jarvis-paused.ico": "5974ee737ee379f643bc12554e2d4138697be28e440f513f4f09236bc6f516bf",
    "tray/jarvis-ready.ico": "01af1c2054c05e8cabb92e36dcfd447ee6df62bbedc7c2dfda1159fd759b3d76",
    "tray/jarvis-talking.ico": "da89856514d45d1364eadddf2662c8cfd4abe670fc82fc3e50cfe311cf967800",
}


def test_published_files_are_byte_identical_to_the_approved_review():
    outputs = APPROVALS["outputs"]
    assert set(APPROVED) == set(outputs) - {f"ui/mark-{n}.png" for n in bi.UI_MARKS}
    for name, digest in APPROVED.items():
        data = (REPO / outputs[name]).read_bytes()
        if name.endswith(".xml"):     # core.autocrlf may check text files out with CRLF
            data = data.replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == digest, outputs[name]


def test_published_ui_marks_are_frames_of_the_approved_icons():
    app = {e["w"]: e["png"] for e in ico_entries((REPO / "assets/icons/jarvis.ico").read_bytes())}
    ready = {e["w"]: e["png"]
             for e in ico_entries((REPO / "assets/icons/tray/jarvis-ready.ico").read_bytes())}
    marks = REPO / "src" / "assets" / "icons"
    assert (marks / "mark-24.png").read_bytes() == ready[24] == app[24]
    for size in (32, 48, 64, 96):        # the reviewed renders inside the approved jarvis.ico
        assert (marks / f"mark-{size}.png").read_bytes() == app[size]
    assert (REPO / "native/setup/emblem-128.png").read_bytes() == app[128]


def test_local_review_build_keeps_the_approved_bytes():
    manifest = REPO / ".runtime" / "icons" / "review" / "manifest.json"
    if not manifest.is_file():
        pytest.skip("no local icon review build")
    outputs = json.loads(manifest.read_text(encoding="utf-8"))["outputs"]
    for name, digest in APPROVED.items():
        assert outputs[name]["sha256"] == digest, name
