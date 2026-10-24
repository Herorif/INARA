"""Budget admission and offline product quality, isolated fixtures with no paid calls."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import pytest
from pydantic import ValidationError
from services.usage import UsageService, usage_counts
from services.usage_contracts import UsagePolicy
from services.conversation import ConversationRequest
from services.tools import ServiceError
from llm.base import LLMResponse
from tests.test_mobile import mobile as mobile_fixture, Phone, pair, post


@pytest.fixture
def usage_app(application_factory):
    return mobile_fixture.__wrapped__(application_factory)


def project(app):
    return app.projects.get_current_project_path()


def configure(app, **changes):
    value = app.usage.snapshot("owner")
    args = {
        "revision": value["policy"]["revision"],
        "enabled": True,
        "daily_microusd": 100,
        "monthly_microusd": 200,
        "per_call_microusd": 60,
        **changes,
    }
    return app.usage.configure("owner", UsagePolicy(**args))


def begin(app, identifier=None, **changes):
    return app.usage.begin(
        "owner",
        project(app),
        "desktop_chat",
        identifier or str(uuid.uuid4()),
        0,
        changes.get("model", "fixture-only"),
    )


def test_default_monitor_unknown_cost_and_sanitized_metadata(usage_app):
    app = usage_app
    assert not app.usage.snapshot("owner")["policy"]["enabled"]
    ticket = begin(app)
    app.usage.finish(ticket, "completed", None, 0.1)
    report = app.usage.snapshot("owner", project(app))
    assert report["project"] == project(app).name and report["invoice_cost_known"] is False
    assert report["monthly_authorized_microusd"] == 0
    assert report["records"][0]["tokens"] is None
    assert not {"owner", "project_scope", "kind", "instance"} & report["records"][0].keys()


def test_daily_monthly_atomic_claims_and_policy_changes_never_reset_spend(usage_app):
    app = usage_app
    configure(app)
    ticket = begin(app)
    app.usage.finish(ticket, "completed", {"total_tokens": 17}, 0.1)
    with pytest.raises(ServiceError, match="Daily"):
        begin(app)
    configure(app, daily_microusd=500, monthly_microusd=100)
    with pytest.raises(ServiceError, match="Monthly"):
        begin(app)
    configure(app, enabled=False)
    assert app.usage.snapshot("owner")["monthly_authorized_microusd"] == 60
    configure(app, daily_microusd=500, monthly_microusd=200)
    assert app.usage.snapshot("owner")["daily_authorized_microusd"] == 60


def test_cross_service_restart_retains_uncertain_allowance_and_duplicate_claim(usage_app):
    app = usage_app
    configure(app)
    first = begin(app, "durable-id")
    app.usage = UsageService(app)
    report = app.usage.snapshot("owner")
    assert report["records"][0]["state"] == "uncertain"
    assert report["daily_authorized_microusd"] == 60
    with pytest.raises(ServiceError, match="already admitted"):
        begin(app, "durable-id")
    with pytest.raises(ServiceError, match="Daily"):
        begin(app)
    assert first["allowance_microusd"] == 60


def test_owner_wide_totals_project_filtered_receipts_and_monthly_carry(usage_app):
    app = usage_app
    day = datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc).timestamp()
    app.usage.clock = lambda: day
    configure(app, daily_microusd=100, monthly_microusd=100)
    first = begin(app)
    other = app.projects.projects_dir / "second"
    other.mkdir()
    assert not app.usage.snapshot("owner", other)["records"]
    assert app.usage.snapshot("owner", other)["monthly_authorized_microusd"] == 60
    app.usage.clock = lambda: day + 120
    assert app.usage.snapshot("owner")["daily_authorized_microusd"] == 0
    assert app.usage.snapshot("owner")["monthly_authorized_microusd"] == 0
    second = begin(app)
    app.usage.finish(first, "completed", None, 1)
    assert app.usage.snapshot("owner")["monthly_authorized_microusd"] == 60
    app.usage.finish(second, "completed", None, 1)
    app.usage.clock = lambda: day - 60
    with pytest.raises(ServiceError, match="clock"):
        begin(app)


def test_new_day_same_month_cannot_bypass_monthly_limit(usage_app):
    app = usage_app
    stamp = datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp()
    app.usage.clock = lambda: stamp
    configure(app, monthly_microusd=100)
    begin(app)
    app.usage.clock = lambda: stamp + 86400
    with pytest.raises(ServiceError, match="Monthly"):
        begin(app)


def test_small_clock_skew_cannot_reopen_previous_budget_period(usage_app):
    app = usage_app
    stamp = datetime(2026, 11, 1, 0, 0, 5, tzinfo=timezone.utc).timestamp()
    app.usage.clock = lambda: stamp
    configure(app)
    begin(app)
    app.usage.clock = lambda: stamp - 10
    with pytest.raises(ServiceError, match="Daily"):
        begin(app)
    assert app.usage.snapshot("owner")["day_utc"] == "2026-11-01"


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": 1},
        {"per_call_microusd": 1.5},
        {"daily_microusd": -1},
        {"per_call_microusd": 0},
        {"max_output_tokens": 12},
        {"monthly_microusd": True},
    ],
)
def test_policy_is_integer_bounded_and_explicit(usage_app, changes):
    with pytest.raises(ValidationError):
        configure(usage_app, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route", ["usage_state", "usage_policy", "quality_state", "quality_run", "quality_cancel"]
)
@pytest.mark.parametrize("sid", ["other", "tray", "unknown"])
async def test_management_routes_require_owner_renderer(usage_app, route, sid):
    assert not (await usage_app.sio.handlers["/"][route](sid, {}))["ok"]


def test_revision_conflict_does_not_overwrite_policy(usage_app):
    app = usage_app
    before = app.usage.snapshot("owner")
    configure(app)
    with pytest.raises(ServiceError, match="changed"):
        app.usage.configure("owner", UsagePolicy(revision=before["policy"]["revision"]))
    assert app.usage.snapshot("owner")["policy"]["enabled"]


@pytest.mark.asyncio
async def test_shared_concurrency_blocks_before_second_provider_call_and_receipts_have_no_content(
    usage_app,
):
    app = usage_app
    configure(app)
    started, finish = asyncio.Event(), asyncio.Event()

    class Provider:
        calls = 0
        _model = "fixture-only"

        async def generate(self, messages, **kwargs):
            Provider.calls += 1
            assert kwargs["max_output_tokens"] == 4096
            started.set()
            await finish.wait()
            return LLMResponse(
                text="Fixture",
                raw=SimpleNamespace(
                    usage_metadata=SimpleNamespace(
                        prompt_token_count=12,
                        candidates_token_count=8,
                        thoughts_token_count=3,
                        cached_content_token_count=2,
                        total_token_count=23,
                    )
                ),
            )

        async def close(self):
            pass

    app.conversation.provider_factory = Provider
    task = asyncio.create_task(
        app.conversation.reply(
            "owner", ConversationRequest(text="PRIVATE_FIXTURE_TEXT"), project(app)
        )
    )
    await started.wait()
    with pytest.raises(ServiceError, match="Daily"):
        await app.conversation.reply(
            "owner", ConversationRequest(text="SECOND_PRIVATE_FIXTURE"), project(app)
        )
    finish.set()
    await task
    report = app.usage.snapshot("owner")
    assert Provider.calls == 1 and report["cloud_calls_this_month"] == 1
    assert report["records"][0]["tokens"]["thinking_tokens"] == 3
    import json

    assert "PRIVATE_FIXTURE" not in json.dumps(report)


@pytest.mark.asyncio
async def test_cancellation_never_refunds_or_replays_an_ambiguous_call(usage_app):
    app = usage_app
    configure(app)
    entered = asyncio.Event()

    class Provider:
        _model = "fixture-only"

        async def generate(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        async def close(self):
            pass

    operation = app.usage.operation("owner", project(app), "desktop_chat", "cancelled-operation")
    task = asyncio.create_task(operation.generate(Provider(), []))
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    report = app.usage.snapshot("owner")
    assert (
        report["daily_authorized_microusd"] == 60 and report["records"][0]["state"] == "uncertain"
    )
    assert not app.usage.active
    with pytest.raises(ServiceError):
        await app.usage.operation(
            "owner", project(app), "desktop_chat", "cancelled-operation"
        ).generate(Provider(), [])


@pytest.mark.asyncio
async def test_phone_chat_uses_owner_budget_and_has_no_budget_control_route(usage_app):
    app = usage_app
    phone = Phone()
    await pair(app, phone, chat=True)
    configure(app, daily_microusd=0)
    app.mobile.chat.provider_factory = lambda: SimpleNamespace(
        generate=AsyncMock(return_value=LLMResponse(text="Never")), close=AsyncMock()
    )
    response = await post(
        app,
        phone,
        "chat",
        {"request_id": str(uuid.uuid4()), "conversation_id": str(uuid.uuid4()), "text": "Fixture"},
    )
    assert response.json()["code"] == "usage_daily_limit"
    assert (await post(app, phone, "usage_policy")).status_code == 404
    assert app.usage.snapshot("owner")["cloud_calls_this_month"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("take_screenshot", {}),
        ("run_web_agent", {"prompt": "fixture"}),
        ("describe_camera", {}),
        ("watch_for", {"description": "fixture"}),
        ("generate_cad_prototype", {"prompt": "fixture"}),
    ],
)
async def test_unmetered_legacy_paths_are_blocked_by_shared_dispatcher(usage_app, name, args):
    app = usage_app
    configure(app)
    app.settings["tool_permissions"].update({key: False for key in app.dispatcher.tools})
    for tool in ("take_screenshot", "run_web_agent", "run_web_agent", "generate_cad"):
        app.settings["tool_permissions"][tool] = False
    with pytest.raises(ServiceError, match="legacy cloud"):
        await app.dispatcher.dispatch(
            "owner", name, args, {"principal": "owner", "project_path": project(app)}
        )


def test_enabling_caps_cannot_race_existing_unmetered_work(usage_app):
    app = usage_app
    with app.usage.tool_scope(
        "take_screenshot", {"principal": "owner", "project_path": project(app)}
    ):
        with pytest.raises(ServiceError, match="Stop legacy"):
            configure(app)
    assert not app.usage.legacy_active
    configure(app)


@pytest.mark.asyncio
async def test_cad_proposal_uses_shared_budget_and_closes_provider(usage_app):
    from services.cad import plan_recipe
    from llm.base import ToolCall

    app = usage_app
    configure(app)
    provider = SimpleNamespace(
        _model="fixture-only",
        generate=AsyncMock(
            return_value=LLMResponse(
                tool_calls=[
                    ToolCall(id="fixture", name="propose_cad_recipe", args={"shape": "box"})
                ]
            )
        ),
        close=AsyncMock(),
    )
    with app.usage.scope("owner", project(app), "cad_plan", "fixture-plan"):
        assert (await plan_recipe("Fixture", lambda: provider))["shape"] == "box"
    provider.close.assert_awaited_once()
    assert app.usage.snapshot("owner")["records"][0]["feature"] == "cad_plan"
    with app.usage.scope("owner", project(app), "cad_plan", "fixture-plan-2"):
        with pytest.raises(ServiceError, match="Daily"):
            await plan_recipe("Fixture", lambda: provider)
    assert provider.generate.await_count == 1


def test_counter_normalization_preserves_missing_as_unknown_and_excludes_private_fields():
    assert usage_counts(LLMResponse(text="No metadata")) is None
    value = usage_counts(
        SimpleNamespace(
            usage_metadata={
                "prompt_token_count": True,
                "candidates_token_count": -1,
                "total_token_count": 20,
                "private_prompt": "SECRET",
                "thoughts_token_count": 3,
            }
        )
    )
    assert value == {"thinking_tokens": 3, "total_tokens": 20}


def test_local_jobs_record_duration_without_consuming_cloud_allowance(usage_app):
    app = usage_app
    configure(app, daily_microusd=0)
    app.usage.local_job(
        "owner",
        project(app),
        "cad_local",
        {
            "request_id": str(uuid.uuid4()),
            "state": "succeeded",
            "created_at": app.usage.clock(),
            "duration_seconds": 0.2,
        },
    )
    report = app.usage.snapshot("owner", project(app))
    assert not report["records"][0]["cloud"] and report["records"][0]["duration_seconds"] == 0.2
    assert report["daily_authorized_microusd"] == 0


@pytest.mark.asyncio
async def test_gemini_output_bound_no_hidden_retry_or_automatic_tool_execution(monkeypatch):
    from google import genai
    from llm.gemini import GeminiProvider

    calls = []
    fake = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(
                generate_content=AsyncMock(
                    return_value=SimpleNamespace(
                        candidates=[], usage_metadata=SimpleNamespace(total_token_count=4)
                    )
                )
            ),
            aclose=AsyncMock(),
        )
    )

    def create(**kwargs):
        calls.append(kwargs)
        return fake

    monkeypatch.setattr(genai, "Client", create)
    provider = GeminiProvider(api_key="fixture-only", model="fixture-only")
    response = await provider.generate(
        [], tools=[{"function_declarations": []}], max_output_tokens=512
    )
    assert calls[0]["http_options"]["retry_options"]["attempts"] == 1
    config = fake.aio.models.generate_content.await_args.kwargs["config"]
    assert config.max_output_tokens == 512 and config.automatic_function_calling.disable is True
    assert usage_counts(response)["total_tokens"] == 4
    await provider.close()


@pytest.mark.asyncio
async def test_fixed_offline_suite_runs_and_cleans_its_disposable_profile():
    from services.quality import run_offline_suite, ROOT

    base = ROOT / ".runtime/quality-checks"
    before = set(base.iterdir()) if base.exists() else set()
    result = await run_offline_suite()
    assert result["passed"] and result["passed_count"] == result["total"] == 12
    assert (
        result["fixture_only"]
        and not result["model_quality_verified"]
        and not result["provider_used"]
    )
    assert set(base.iterdir()) == before


@pytest.mark.asyncio
async def test_quality_disconnect_cancels_child_work_without_replaying(usage_app, monkeypatch):
    import services.quality as quality_module

    app = usage_app
    entered, stopped = asyncio.Event(), asyncio.Event()

    async def run():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(quality_module, "run_offline_suite", run)
    task = asyncio.create_task(app.sio.handlers["/"]["quality_run"]("desktop", {}))
    await entered.wait()
    await app.quality.stop_sid("desktop")
    assert stopped.is_set() and (await task)["code"] == "quality_cancelled"
    assert not app.quality.running


@pytest.mark.asyncio
async def test_transcription_stream_is_metered_and_denied_before_sdk_client(usage_app, monkeypatch):
    from google import genai
    from services import speech_provider

    app = usage_app
    configure(app)
    clients, streams = [], []

    async def stream(**kwargs):
        streams.append(kwargs)

        async def chunks():
            yield SimpleNamespace(text="Synthetic transcript", usage_metadata=None)
            yield SimpleNamespace(
                text="",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=5, candidates_token_count=3, total_token_count=8
                ),
            )

        return chunks()

    fake = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content_stream=stream), aclose=AsyncMock()
        )
    )

    def create(**kwargs):
        clients.append(kwargs)
        return fake

    monkeypatch.setattr(genai, "Client", create)
    monkeypatch.setattr(speech_provider, "ready", lambda: None)
    with app.usage.scope("owner", project(app), "transcription", "fixture-turn"):
        assert await speech_provider.transcribe(bytes(640), AsyncMock()) == "Synthetic transcript"
    assert streams[0]["config"]["max_output_tokens"] == 4096
    assert clients[0]["http_options"]["retry_options"]["attempts"] == 1
    assert app.usage.snapshot("owner")["records"][0]["tokens"]["total_tokens"] == 8
    with app.usage.scope("owner", project(app), "transcription", "fixture-turn-two"):
        with pytest.raises(ServiceError, match="Daily"):
            await speech_provider.transcribe(bytes(640), AsyncMock())
    assert len(clients) == 1
    fake.aio.aclose.assert_awaited_once()


def test_budget_clock_failure_does_not_disable_local_tools(usage_app):
    app = usage_app
    configure(app)
    app.usage.clock = lambda: 0
    with app.usage.tool_scope("generate_cad", {"principal": "owner", "project_path": project(app)}):
        pass
    with pytest.raises(ServiceError, match="clock"):
        begin(app)


@pytest.mark.asyncio
async def test_cancelled_quality_runner_closes_its_owned_process_and_removes_fixture_directory(
    monkeypatch,
):
    from services.quality import run_offline_suite, ROOT
    import resident.win32 as win32

    closed, entered = [], asyncio.Event()

    class Child:
        def __init__(self, *args):
            entered.set()

        def alive(self):
            return True

        def close(self):
            closed.append(True)

    monkeypatch.setattr(win32, "WorkspaceProcess", Child)
    base = ROOT / ".runtime/quality-checks"
    before = set(base.iterdir())
    task = asyncio.create_task(run_offline_suite())
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert closed and set(base.iterdir()) == before
