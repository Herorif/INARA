"""Contained staged printing with durable no-replay; no slicer/printer is used."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid
import pytest
from services.device_contracts import PrintRequest, PrintStage
from services.printing import OwnedSlicer, PrintService
from services.printer_protocol import start_uploaded
from services.tools import ServiceError
from pydantic import ValidationError


@pytest.fixture
def printing(application_factory):
    app = application_factory()
    owner = str(uuid.uuid4())
    app.sessions.accept("ui", {"client_id": owner})
    root = app.projects.get_current_project_path()
    (root / "cad/source.stl").write_bytes(b"fixture STL bytes; no actual geometry/slicing claim")
    target = SimpleNamespace(
        name="Fixture", host="10.0.0.9", port=7125, printer_type="moonraker", api_key=None
    )
    app.compat_service.printer = SimpleNamespace(
        _resolve_printer=lambda _: target,
        upload_gcode=AsyncMock(return_value=True),
        start_print=AsyncMock(return_value=True),
    )
    app.compat_service.start_monitor = Mock()

    async def slice_fixture(plan):
        plan.gcode.write_text("; fixture gcode, no machine execution")

    app.printing.slicer = SimpleNamespace(run=AsyncMock(side_effect=slice_fixture))
    app.settings["tool_permissions"].update(
        {key: False for key in ("print_stl", "slice_stl", "upload_gcode", "start_print")}
    )
    return app, app.sessions.context("ui").tools(), target


async def run(app, context, args=None, approve=None):
    return await app.dispatcher.dispatch(
        context["principal"],
        "print_stl",
        (args or PrintRequest(printer="Fixture")).model_dump(mode="json"),
        context,
        approve,
    )


@pytest.mark.asyncio
async def test_stage_order_upload_does_not_start_and_duplicate_never_replays(printing):
    app, context, _ = printing
    request = PrintRequest(printer="Fixture")
    result = await run(app, context, request)
    assert result["status"] == "success"
    app.compat_service.printer.upload_gcode.assert_awaited_once()
    assert app.compat_service.printer.upload_gcode.await_args.kwargs == {"start_print": False}
    name = app.compat_service.printer.start_print.await_args.args[1]
    assert len(name) == 38 and name.endswith(".gcode")
    assert await run(app, context, request) == result
    app.printing.slicer.run.assert_awaited_once()
    app.compat_service.printer.start_print.assert_awaited_once()
    app.printing.active = None
    with pytest.raises(ServiceError, match="already has different"):
        await run(app, context, request.model_copy(update={"stl_path": "different.stl"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["print_stl", "slice_stl", "upload_gcode", "start_print"])
async def test_each_permission_can_stop_following_phases(printing, stage):
    app, context, _ = printing
    app.settings["tool_permissions"][stage] = "deny"
    with pytest.raises(ServiceError) as failure:
        await run(app, context)
    assert failure.value.code == "permission_denied"
    if stage in ("print_stl", "slice_stl"):
        app.printing.slicer.run.assert_not_called()
    if stage != "start_print":
        app.compat_service.printer.upload_gcode.assert_not_called()
    app.compat_service.printer.start_print.assert_not_called()


@pytest.mark.asyncio
async def test_every_approval_names_exact_phase_and_foreign_owner_cannot_approve(printing):
    app, context, _ = printing
    app.settings["tool_permissions"].update(
        {key: True for key in ("print_stl", "slice_stl", "upload_gcode", "start_print")}
    )
    names = []

    async def approve(payload):
        names.append(payload["tool"])
        assert not app.dispatcher.resolve("foreign", payload["id"], True)
        assert app.dispatcher.resolve(context["principal"], payload["id"], True)

    await run(app, context, approve=approve)
    assert names == ["print_stl", "slice_stl", "upload_gcode", "start_print"]


@pytest.mark.parametrize(
    "value",
    [
        "../escape.stl",
        "C:\\outside.stl",
        "//server/share.stl",
        "part.stl:stream",
        "cad/../../escape.stl",
    ],
)
def test_print_path_validation_before_approval(value):
    with pytest.raises(ValidationError):
        PrintRequest(printer="Fixture", stl_path=value)


@pytest.mark.asyncio
async def test_symlink_escape_and_profile_escape_do_not_slice(printing, tmp_path):
    app, context, _ = printing
    outside = tmp_path / "outside.stl"
    outside.write_bytes(b"outside")
    link = context["project_path"] / "cad/escape.stl"
    try:
        link.symlink_to(outside)
    except OSError:
        import subprocess

        directory = tmp_path / "junction-target"
        directory.mkdir()
        (directory / "outside.stl").write_bytes(b"outside")
        junction = context["project_path"] / "cad/junction"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(directory)], capture_output=True
        )
        assert result.returncode == 0, "Could not create the isolated junction fixture"
        link = junction / "outside.stl"
    with pytest.raises(ServiceError) as failure:
        await run(
            app,
            context,
            PrintRequest(
                printer="Fixture", stl_path=str(link.relative_to(context["project_path"]))
            ),
        )
    assert failure.value.code == "path_denied"
    app.printing.slicer.run.assert_not_called()


@pytest.mark.asyncio
async def test_source_and_gcode_are_snapshot_bound_while_waiting_approval(printing):
    app, context, _ = printing
    app.settings["tool_permissions"]["upload_gcode"] = True

    async def approve(payload):
        path = context["project_path"] / payload["args"]["path"]
        path.write_text("changed after review")
        app.dispatcher.resolve(context["principal"], payload["id"], True)

    with pytest.raises(ServiceError) as failure:
        await run(app, context, approve=approve)
    assert failure.value.code == "print_changed"
    app.compat_service.printer.upload_gcode.assert_not_called()


@pytest.mark.asyncio
async def test_target_changes_between_stage_approval_and_execution_are_rejected(printing):
    app, context, target = printing
    app.settings["tool_permissions"]["upload_gcode"] = True

    async def approve(payload):
        target.host = "10.0.0.99"
        app.dispatcher.resolve(context["principal"], payload["id"], True)

    with pytest.raises(ServiceError) as failure:
        await run(app, context, approve=approve)
    assert failure.value.code == "printer_changed"
    app.compat_service.printer.upload_gcode.assert_not_called()


@pytest.mark.asyncio
async def test_failed_start_is_uncertain_and_persists_across_service_restart(printing):
    app, context, _ = printing
    request = PrintRequest(printer="Fixture")
    app.compat_service.printer.start_print.return_value = False
    with pytest.raises(ServiceError):
        await run(app, context, request)
    app.printing = PrintService(
        app.database,
        app.resources,
        app.dispatcher,
        app.compat_service,
        app.delivery.publish_job,
        app.printing.slicer,
    )
    with pytest.raises(ServiceError) as failure:
        await run(app, context, request)
    assert failure.value.code == "request_uncertain"
    app.compat_service.printer.start_print.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_during_upload_never_reaches_start_and_never_replays(printing):
    app, context, _ = printing
    entered = asyncio.Event()

    async def upload(*args, **kwargs):
        entered.set()
        await asyncio.sleep(60)

    app.compat_service.printer.upload_gcode.side_effect = upload
    request = PrintRequest(printer="Fixture")
    task = asyncio.create_task(run(app, context, request))
    await asyncio.wait_for(entered.wait(), 1)
    await app.printing.close()
    assert task.cancelled()
    app.compat_service.printer.start_print.assert_not_called()
    with pytest.raises(ServiceError) as failure:
        await run(app, context, request)
    assert failure.value.code == "request_uncertain"
    assert not app.resources.creative_lock.locked()


@pytest.mark.asyncio
async def test_hidden_stage_cannot_be_called_without_bound_plan(printing):
    app, context, _ = printing
    assert not {"slice_stl", "upload_gcode", "start_print"} & {
        item["name"] for item in app.dispatcher.schemas()
    }
    with pytest.raises(ServiceError) as failure:
        await app.dispatcher.dispatch(
            context["principal"],
            "start_print",
            PrintStage(
                request_id=uuid.uuid4(), printer="Fixture", path="x.gcode", sha256="0" * 64
            ).model_dump(mode="json"),
            context,
        )
    assert failure.value.code == "print_scope"


@pytest.mark.asyncio
async def test_owned_slicer_timeout_closes_entire_process_contract(printing):
    app, context, _ = printing
    plan = app.printing.prepare(PrintRequest(printer="Fixture"), context)
    process = SimpleNamespace(alive=lambda: True, close=Mock())
    runner = OwnedSlicer(process_factory=lambda *args: process, timeout=0)
    with pytest.raises(ServiceError) as failure:
        await runner.run(plan)
    assert failure.value.code == "slicer_timeout"
    process.close.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol,endpoint,payload",
    [
        ("moonraker", "/printer/print/start", {"filename": "a" * 32 + ".gcode"}),
        (
            "octoprint",
            "/api/files/local/" + "a" * 32 + ".gcode",
            {"command": "select", "print": True},
        ),
    ],
)
async def test_start_protocol_is_separate_fixed_request(protocol, endpoint, payload):
    calls = []

    class Response:
        status = 204

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Session(Response):
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    printer = SimpleNamespace(printer_type=protocol, host="printer.test", port=80, api_key=None)
    assert await start_uploaded(printer, "a" * 32 + ".gcode", Session)
    assert calls == [("http://printer.test:80" + endpoint, {"json": payload, "headers": {}})]
    assert not await start_uploaded(printer, "../unsafe.gcode", Session)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_real_owned_slicer_process_lifetime_with_labelled_fixture(printing):
    from resident.win32 import WorkspaceProcess
    from pathlib import Path

    app, context, _ = printing
    plan = app.printing.prepare(PrintRequest(printer="Fixture"), context)
    processes = []

    def launch(executable, entrypoint, bootstrap, cwd):
        assert entrypoint.name == "print_slice_worker.py"
        process = WorkspaceProcess(
            executable, Path(__file__).parent / "fixtures/print_slice_fixture.py", bootstrap, cwd
        )
        processes.append(process)
        return process

    await OwnedSlicer(process_factory=launch).run(plan)
    assert plan.gcode.read_text().startswith("; OWNED PROCESS FIXTURE")
    assert len(processes) == 1 and not processes[0].alive()


@pytest.mark.asyncio
async def test_profile_snapshot_cannot_change_after_stage_review(printing):
    app, context, _ = printing
    (context["project_path"] / "settings.ini").write_text("; approved fixture profile")
    app.settings["tool_permissions"]["slice_stl"] = True

    async def approve(payload):
        profile = (context["project_path"] / payload["args"]["path"]).parent / "profile.ini"
        profile.write_text("; changed profile")
        app.dispatcher.resolve(context["principal"], payload["id"], True)

    with pytest.raises(ServiceError) as failure:
        await run(app, context, PrintRequest(printer="Fixture", profile="settings.ini"), approve)
    assert failure.value.code == "print_changed"
    app.printing.slicer.run.assert_not_called()


@pytest.mark.asyncio
async def test_exact_installed_profile_selection_is_snapshotted(printing, tmp_path):
    app, context, _ = printing
    catalog = tmp_path / "catalog"
    profile = catalog / "system/vendor/machine/profile.json"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"fixture":true}')
    app.compat_service.printer._orca_profiles_dir = str(catalog)
    app.compat_service.printer.get_available_profiles = lambda: {
        "machines": ["system/vendor/machine/profile.json"]
    }
    result = await run(
        app, context, PrintRequest(printer="Fixture", profile="system/vendor/machine/profile.json")
    )
    assert result["status"] == "success"
    plan = app.printing.slicer.run.await_args.args[0]
    assert plan.profile.is_relative_to(context["project_path"])
    assert plan.profile.read_text() == '{"fixture":true}'
