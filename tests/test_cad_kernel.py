"""The CAD kernel service (services/cad_kernel.py) and its build123d worker.

Most tests drive tests/fixtures/fake_cad_kernel_worker.py, run by the core interpreter: it
speaks the worker protocol without build123d. The real-kernel tests at the end run
backend/workers/cad_kernel_worker.py in .venv-cad and are skipped when it isn't installed.
"""

import asyncio
import math
import sys
import time
from pathlib import Path

import psutil
import pytest
import pytest_asyncio

from services.cad_features import parse_tree
from services.cad_kernel import VENV, CadKernel, CadKernelError, plain_error, venv_python

FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_cad_kernel_worker.py"


def box_tree(ident="body", size=(20, 20, 10), *more, export=("glb",)):
    features = [{"id": ident, "op": "box", "size": list(size)}, *more]
    return {"units": "mm", "features": features, "export": list(export)}


def fake_kernel(tmp_path, **options):
    return CadKernel(python=sys.executable, worker=FAKE, root=tmp_path / "jobs", **options)


async def eventually(check, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        await asyncio.sleep(0.05)
    return check()


def gone(pid):
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


async def grandchild_pid(kernel):
    path = kernel.root / "grandchild.pid"
    assert await eventually(path.is_file, 10)
    await eventually(lambda: path.read_text(encoding="utf-8").strip() != "", 2)
    return int(path.read_text(encoding="utf-8"))


# --- fake worker --------------------------------------------------------------------------

async def test_starts_on_demand_and_reuses_one_worker(tmp_path):
    kernel = fake_kernel(tmp_path)
    try:
        assert kernel.available() and not kernel.running()
        first = await kernel.build(box_tree(), quality="draft")
        pid = kernel.process.pid
        second = await kernel.build(box_tree(size=(30, 20, 10)), quality="draft")
        assert kernel.process.pid == pid and kernel.starts == 1
        assert first["files"]["glb"].read_bytes() == b"glTF"
        assert first["files"]["glb"].is_relative_to(kernel.root.resolve())
        assert first["hash"] != second["hash"] and not second["cached"]
        assert kernel.status() == {"available": True, "reason": None, "running": True,
                                   "version": "fake-1"}
    finally:
        await kernel.close()
    assert not kernel.running()


async def test_noise_on_stdout_and_foreign_ids_are_skipped(tmp_path):
    kernel = fake_kernel(tmp_path)
    try:
        result = await kernel.build(box_tree("noise"), quality="draft")
        assert result["facts"]["volume"] == 1.0
    finally:
        await kernel.close()


async def test_a_timeout_kills_the_worker_tree_and_the_next_build_restarts(tmp_path):
    kernel = fake_kernel(tmp_path, timeouts={"draft": 2.0})
    try:
        await kernel.build(box_tree(), quality="draft")
        worker = kernel.process.pid
        build = asyncio.ensure_future(kernel.build(box_tree("slow"), quality="draft"))
        grandchild = await grandchild_pid(kernel)
        with pytest.raises(CadKernelError) as caught:
            await build
        assert caught.value.code == "cad_kernel_timeout"
        assert "2 s" in str(caught.value)
        assert await eventually(lambda: gone(worker) and gone(grandchild))
        assert not kernel.running()
        await kernel.build(box_tree(size=(5, 5, 5)), quality="draft")
        assert kernel.starts == 2 and kernel.process.pid != worker
    finally:
        await kernel.close()


async def test_cancelling_a_build_kills_the_worker_tree(tmp_path):
    kernel = fake_kernel(tmp_path)
    try:
        build = asyncio.ensure_future(kernel.build(box_tree("slow"), quality="final"))
        grandchild = await grandchild_pid(kernel)
        worker = kernel.process.pid
        build.cancel()
        with pytest.raises(asyncio.CancelledError):
            await build
        assert await eventually(lambda: gone(worker) and gone(grandchild))
        assert not kernel.running()
    finally:
        await kernel.close()


async def test_a_crash_is_reported_plainly_and_the_worker_restarts(tmp_path):
    kernel = fake_kernel(tmp_path)
    try:
        with pytest.raises(CadKernelError) as caught:
            await kernel.build(box_tree("crash"), quality="draft")
        assert caught.value.code == "cad_kernel_crashed"
        assert "restart" in str(caught.value)
        assert kernel.available()
        result = await kernel.build(box_tree(), quality="draft")
        assert result["facts"]["valid"] and kernel.starts == 2
    finally:
        await kernel.close()


async def test_a_worker_that_died_while_idle_is_replaced_silently(tmp_path):
    kernel = fake_kernel(tmp_path)
    try:
        await kernel.build(box_tree(), quality="draft")
        kernel.process.kill()
        await kernel.process.wait()
        await kernel.build(box_tree(size=(3, 3, 3)), quality="draft")
        assert kernel.starts == 2
    finally:
        await kernel.close()


async def test_kernel_failures_become_plain_messages(tmp_path):
    kernel = fake_kernel(tmp_path)
    tree = box_tree("fail", (60, 40, 4),
                    {"id": "f", "op": "fillet", "target": "fail", "edges": "all", "radius": 3})
    try:
        with pytest.raises(CadKernelError) as caught:
            await kernel.build(tree, quality="draft")
    finally:
        await kernel.close()
    error = caught.value
    assert error.code == "cad_kernel_failed" and error.kernel_code == "kernel_failed"
    assert str(error) == "A 3 mm fillet doesn't fit the 4 mm edge on fail."
    assert (error.feature, error.index) == ("f", 1)


def test_error_mapping_names_the_step_in_plain_words():
    tree = parse_tree(box_tree(
        "body", (20, 20, 10),
        {"id": "h", "op": "hole", "target": "body", "at": [10, 10], "diameter": 6},
        {"op": "chamfer", "target": "body", "edges": "vertical", "distance": 8},
        {"op": "shell", "target": "body", "thickness": 3},
    ))
    chamfer = plain_error({"code": "kernel_failed", "index": 2,
                           "detail": {"op": "chamfer", "size": 8, "room": 10}}, tree)
    assert str(chamfer) == "An 8 mm chamfer doesn't fit the 10 mm edge on body."
    edges = plain_error({"code": "no_edges", "index": 2, "detail": {"edges": "vertical"}}, tree)
    assert str(edges) == "There are no vertical corner edges on body to chamfer."
    shell = plain_error({"code": "kernel_failed", "index": 3,
                         "detail": {"op": "shell", "size": 3}}, tree)
    assert str(shell) == (
        "JARVIS couldn't shell body to 3 mm walls. Try thinner walls or shell before rounding "
        "the edges."
    )
    other = plain_error({"code": "kernel_failed", "index": 1, "message": "BRep_API: not done"},
                        tree)
    assert str(other) == (
        "Step 2 (through hole Ø6 mm on the top face at (10, 10)) couldn't be built. Try "
        "smaller sizes or a different order."
    )
    assert "BRep" not in str(other)
    empty = plain_error({"code": "empty_result", "index": 1}, tree)
    assert str(empty).startswith("Step 2 (through hole") and str(empty).endswith("of body.")


async def test_drafts_are_cached_by_tree_hash_and_export_choices_do_not_bust_it(tmp_path):
    kernel = fake_kernel(tmp_path)
    try:
        first = await kernel.build(box_tree(export=("glb", "stl")), quality="draft")
        sent = kernel.next_id
        same = {"export": ["step"], "features": [{"size": [20.0, 20, 10.0], "op": "box",
                                                  "id": "body"}], "units": "mm"}
        again = await kernel.build(same, export=["stl"], quality="draft")
        assert again["cached"] and again["hash"] == first["hash"]
        assert again["files"] == first["files"] and set(again["files"]) == {"glb"}
        assert kernel.next_id == sent  # the worker wasn't asked again
        final = await kernel.build(box_tree(), export=["glb", "step"], quality="final")
        assert set(final["files"]) == {"glb", "step"} and not final["cached"]
        await kernel.build(box_tree(), export=["step", "glb"], quality="final")
        assert kernel.next_id == sent + 2  # final builds are never cached
        first["files"]["glb"].unlink()
        rebuilt = await kernel.build(box_tree(), quality="draft")
        assert not rebuilt["cached"] and rebuilt["files"]["glb"].is_file()
    finally:
        await kernel.close()


async def test_invalid_trees_and_options_are_refused_before_the_worker(tmp_path):
    kernel = fake_kernel(tmp_path)
    try:
        with pytest.raises(CadKernelError) as caught:
            await kernel.build({"features": [{"op": "hole", "target": "x"}]})
        assert caught.value.code == "cad_tree_invalid"
        with pytest.raises(CadKernelError):
            await kernel.build(box_tree(), quality="best")
        with pytest.raises(CadKernelError):
            await kernel.build(box_tree(), export=["obj"], quality="final")
        assert not kernel.running()
    finally:
        await kernel.close()


async def test_a_missing_venv_leaves_the_kernel_unavailable_with_a_reason(tmp_path):
    kernel = CadKernel(venv=tmp_path / "no-venv", root=tmp_path / "jobs")
    assert not kernel.available()
    assert ".venv-cad" in kernel.reason
    assert kernel.status()["available"] is False
    with pytest.raises(CadKernelError) as caught:
        await kernel.build(box_tree(), quality="draft")
    assert caught.value.code == "cad_kernel_unavailable"
    await kernel.close()


async def test_a_worker_that_cannot_start_disables_the_kernel_for_a_while(tmp_path):
    broken = tmp_path / "broken_worker.py"
    broken.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    now = [100.0]
    kernel = CadKernel(python=sys.executable, worker=broken, root=tmp_path / "jobs",
                       retry_after=60, clock=lambda: now[0])
    try:
        with pytest.raises(CadKernelError) as caught:
            await kernel.build(box_tree(), quality="draft")
        assert caught.value.code == "cad_kernel_unavailable"
        assert not kernel.available() and "box engine" in kernel.reason
        now[0] += 61
        assert kernel.available()
    finally:
        await kernel.close()


async def test_the_worker_stops_after_being_idle(tmp_path):
    kernel = fake_kernel(tmp_path, idle_seconds=0.3, idle_tick=0.05)
    try:
        await kernel.build(box_tree(), quality="draft")
        pid = kernel.process.pid
        assert await eventually(lambda: not kernel.running(), 5)
        assert await eventually(lambda: gone(pid))
        await kernel.build(box_tree(size=(4, 4, 4)), quality="draft")
        assert kernel.starts == 2
    finally:
        await kernel.close()


# --- real kernel (opt-in: needs .venv-cad with build123d) ---------------------------------

REAL = venv_python(VENV).is_file()
real = pytest.mark.skipif(
    not REAL, reason=".venv-cad (build123d 0.13.0) isn't installed; real-kernel tests skipped"
)
module_loop = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def kernel(tmp_path_factory):
    service = CadKernel(root=tmp_path_factory.mktemp("cad-kernel"))
    started = time.perf_counter()
    await service.ping()
    service.startup_seconds = time.perf_counter() - started
    yield service
    await service.close()


def hole(ident="h1", at=(10, 10), diameter=6, target="body", **more):
    return {"id": ident, "op": "hole", "target": target, "face": "top", "at": list(at),
            "diameter": diameter, "depth": "through", **more}


@real
@module_loop
async def test_real_through_hole_volume_and_timings(kernel):
    tree = box_tree("body", (20, 20, 10), hole())
    draft = await kernel.build(tree, quality="draft")
    final = await kernel.build(tree, export=["glb", "stl", "step"], quality="final")
    expected = 20 * 20 * 10 - math.pi * 3**2 * 10
    assert draft["facts"]["volume"] == pytest.approx(expected, abs=0.01)
    assert round(expected, 1) == 3717.3
    assert draft["facts"]["bbox"] == [20, 20, 10] and draft["facts"]["valid"]
    assert draft["files"]["glb"].read_bytes()[:4] == b"glTF"
    assert set(final["files"]) == {"glb", "stl", "step"}
    print(f"\nreal kernel: start {kernel.startup_seconds:.2f}s, draft {draft['seconds']:.2f}s, "
          f"final {final['seconds']:.2f}s")


@real
@module_loop
async def test_real_vertical_fillet_skips_the_hole_seam(kernel):
    tree = box_tree("body", (20, 20, 10), hole(),
                    {"id": "round", "op": "fillet", "target": "body", "edges": "vertical",
                     "radius": 3})
    result = await kernel.build(tree, quality="draft")
    corners = 4 * (3**2 - math.pi * 3**2 / 4) * 10
    assert result["facts"]["valid"]
    assert result["facts"]["volume"] == pytest.approx(
        20 * 20 * 10 - math.pi * 9 * 10 - corners, abs=0.01
    )


@real
@module_loop
async def test_real_step_export_reimports_with_the_same_volume(kernel):
    tree = box_tree("body", (60, 40, 20), hole(at=(10, 5), diameter=5),
                    {"op": "chamfer", "target": "body", "edges": "top", "distance": 1})
    result = await kernel.build(tree, export=["step"], quality="final")
    probe = (
        "import sys\nfrom build123d import import_step\n"
        "print(import_step(sys.argv[1]).volume)\n"
    )
    process = await asyncio.create_subprocess_exec(
        str(venv_python(VENV)), "-I", "-c", probe, str(result["files"]["step"]),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    output, _ = await asyncio.wait_for(process.communicate(), 120)
    assert float(output.decode().strip().splitlines()[-1]) == pytest.approx(
        result["facts"]["volume"], rel=1e-6
    )


@real
@module_loop
async def test_real_too_large_fillet_names_the_feature(kernel):
    tree = box_tree("body", (60, 40, 4),
                    {"id": "edges", "op": "fillet", "target": "body", "radius": 3})
    with pytest.raises(CadKernelError) as caught:
        await kernel.build(tree, quality="draft")
    error = caught.value
    assert error.kernel_code == "kernel_failed" and error.feature == "edges"
    assert error.index == 1
    assert str(error) == "A 3 mm fillet doesn't fit the 4 mm edge on body."
    assert kernel.running()  # a refused feature doesn't cost the worker


@real
@module_loop
async def test_real_shell_is_open_at_the_top(kernel):
    tree = box_tree("body", (20, 20, 10),
                    {"op": "shell", "target": "body", "thickness": 2, "open": "top"})
    result = await kernel.build(tree, quality="draft")
    assert result["facts"]["volume"] == pytest.approx(20 * 20 * 10 - 16 * 16 * 8, abs=0.01)
    assert result["facts"]["bbox"] == [20, 20, 10]


@real
@module_loop
async def test_real_engraved_text_reduces_the_volume(kernel):
    tree = box_tree("body", (60, 40, 10),
                    {"op": "text", "target": "body", "text": "JARVIS", "size": 8,
                     "depth": 0.6})
    result = await kernel.build(tree, quality="draft")
    assert result["facts"]["valid"]
    assert 60 * 40 * 10 - 60 < result["facts"]["volume"] < 60 * 40 * 10 - 5
    assert result["facts"]["bbox"] == [60, 40, 10]


@real
@module_loop
async def test_real_linear_pattern_makes_four_holes(kernel):
    tree = box_tree("body", (60, 40, 10), hole(at=(10, 5), diameter=5),
                    {"op": "pattern", "of": "h1", "kind": "linear", "count": [2, 2],
                     "spacing": [40, 30]})
    result = await kernel.build(tree, quality="draft")
    assert result["facts"]["volume"] == pytest.approx(
        60 * 40 * 10 - 4 * math.pi * 2.5**2 * 10, abs=0.01
    )
    assert result["facts"]["faces"] == 6 + 4


@real
@module_loop
async def test_real_shell_that_occ_skips_is_a_plain_failure_and_misses_warn(kernel):
    rounded = box_tree("body", (60, 40, 20),
                       {"op": "fillet", "target": "body", "edges": "vertical", "radius": 3},
                       {"op": "chamfer", "target": "body", "edges": "top", "distance": 1},
                       {"id": "walls", "op": "shell", "target": "body", "thickness": 2})
    with pytest.raises(CadKernelError) as caught:
        await kernel.build(rounded, quality="draft")
    assert caught.value.feature == "walls"
    assert str(caught.value).startswith("JARVIS couldn't shell body to 2 mm walls.")
    missed = box_tree("body", (20, 20, 10),
                      {"id": "away", "op": "cut", "target": "body",
                       "tool": {"op": "box", "size": [5, 5, 5], "at": [100, 0, 0]}})
    result = await kernel.build(missed, quality="draft")
    assert result["warnings"] == [{"code": "no_effect", "index": 1, "feature": "away"}]
