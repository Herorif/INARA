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
    assert manifest["outputs"]["jarvis-mark-20.png"]["pixels"] == [20, 20]
    expected = {"jarvis.ico", "jarvis.png", "jarvis-mark-20.png", "jarvis-mark-40.png",
                "setup/emblem-64.png", "setup/emblem-128.png"} \
        | {f"tray/jarvis-{s}.ico" for s in ("ready", "talking", "paused", "calls", "attention")}
    assert expected <= set(manifest["outputs"])


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
