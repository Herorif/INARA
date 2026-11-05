"""
Tests for the legacy CAD generation agent.

Offline tests drive CadAgent through its injectable ``client`` (a fake Gemini
stream) and ``runner`` (a fake child-process runner), so they never reach the
network and never execute model-written Python.

Tests marked ``live_api`` call the real Gemini API, spend money and run the
generated script; they are skipped unless JARVIS_LIVE_API_TESTS=1.
"""
import base64
import os
import re
from types import SimpleNamespace

import pytest

from cad_agent import CadAgent
from services.tools import ServiceError


CUBE_CODE = "from build123d import *\nresult_part = Box(10, 10, 10)\nexport_stl(result_part, 'output.stl')"
STL_BYTES = b"solid cube\nendsolid cube\n"


def fenced(code):
    return f"Here is the script:\n```python\n{code}\n```\n"


def chunk(*parts):
    """One streamed chunk; each part is (text, is_thought)."""
    content = SimpleNamespace(parts=[SimpleNamespace(text=t, thought=th) for t, th in parts])
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


class FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class FakeClient:
    """Mimics ``client.aio.models.generate_content_stream``; one response list per call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content_stream=self._stream))

    async def _stream(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return FakeStream(self.responses.pop(0))


class FakeRunner:
    """Records each run; a successful run writes the STL the script would export."""

    def __init__(self, results=None, write_stl=True):
        self.results = list(results or [])
        self.write_stl = write_stl
        self.calls = []

    async def run(self, script_path, work_dir):
        with open(script_path) as f:  # noqa: ASYNC230  test fake for the child-process runner
            script = f.read()
        self.calls.append({"script_path": script_path, "work_dir": work_dir, "script": script})
        returncode, stderr = self.results.pop(0) if self.results else (0, "")
        if returncode == 0 and self.write_stl:
            target = re.search(r"export_stl\(result_part, '([^']+)'\)", script).group(1)
            with open(target.replace("\\\\", "\\"), "wb") as f:  # noqa: ASYNC230  test fake for the child-process runner
                f.write(STL_BYTES)
        return returncode, stderr


def make_agent(responses, runner=None):
    thoughts, statuses = [], []
    client = FakeClient(responses)
    agent = CadAgent(
        on_thought=thoughts.append,
        on_status=statuses.append,
        client=client,
        runner=runner or FakeRunner(),
    )
    return agent, client, thoughts, statuses


class TestCadAgentInit:
    def test_injected_client_and_runner_are_used(self):
        client, runner = FakeClient([]), FakeRunner()
        agent = CadAgent(client=client, runner=runner)
        assert agent.client is client
        assert agent.runner is runner
        assert agent.model  # resolved from the capability profile
        assert "result_part" in agent.system_instruction
        assert "export_stl(result_part, 'output.stl')" in agent.system_instruction


class TestRequestCode:
    async def test_streams_thoughts_and_returns_answer_text(self):
        agent, client, thoughts, _ = make_agent([[
            chunk(("thinking about a cube", True), ("```python\nfrom build123d", False)),
            chunk(("", False), (" import *\n```", False)),
        ]])

        answer = await agent.request_code("a cube")

        assert answer == "```python\nfrom build123d import *\n```"
        assert thoughts == ["thinking about a cube"]
        call = client.calls[0]
        assert call["model"] == agent.model
        assert call["contents"] == "a cube"
        assert call["config"].system_instruction == agent.system_instruction
        assert call["config"].thinking_config.include_thoughts is True


class TestGeneratePrototype:
    async def test_success_writes_script_runs_it_and_returns_stl(self, tmp_path):
        runner = FakeRunner()
        agent, client, _, statuses = make_agent([[chunk((fenced(CUBE_CODE), False))]], runner)

        result = await agent.generate_prototype("A simple 10mm cube", output_dir=str(tmp_path))

        assert result["format"] == "stl"
        assert base64.b64decode(result["data"]) == STL_BYTES
        assert os.path.dirname(result["file_path"]) == str(tmp_path)
        assert re.fullmatch(r"output_\d{8}_\d{6}\.stl", os.path.basename(result["file_path"]))
        assert "A simple 10mm cube" in client.calls[0]["contents"]

        script_path = str(tmp_path / "current_design.py")
        assert runner.calls == [{"script_path": script_path, "work_dir": str(tmp_path),
                                 "script": runner.calls[0]["script"]}]
        script = runner.calls[0]["script"]
        assert "'output.stl'" not in script  # the real output path was injected
        assert result["file_path"].replace("\\", "\\\\") in script
        assert statuses == [{"status": "generating", "attempt": 1, "max_attempts": 3, "error": None}]

    async def test_failed_run_feeds_the_error_back_and_retries(self, tmp_path):
        runner = FakeRunner(results=[(1, "Traceback (most recent call last):\nValueError: fillet too big"), (0, "")])
        agent, client, _, statuses = make_agent(
            [[chunk((fenced(CUBE_CODE), False))], [chunk((fenced(CUBE_CODE), False))]], runner)

        result = await agent.generate_prototype("A gear", output_dir=str(tmp_path))

        assert result is not None and base64.b64decode(result["data"]) == STL_BYTES
        assert len(runner.calls) == 2
        retry_prompt = client.calls[1]["contents"]
        assert "ValueError: fillet too big" in retry_prompt
        assert "Original request: A gear" in retry_prompt
        assert {"status": "retrying", "attempt": 1, "max_attempts": 3,
                "error": "ValueError: fillet too big"} in statuses
        assert statuses[-1] == {"status": "retrying", "attempt": 2, "max_attempts": 3, "error": None}

    async def test_gives_up_after_three_failed_runs(self, tmp_path):
        runner = FakeRunner(results=[(1, "boom")] * 3)
        agent, client, _, statuses = make_agent([[chunk((fenced(CUBE_CODE), False))]] * 3, runner)

        assert await agent.generate_prototype("A cube", output_dir=str(tmp_path)) is None
        assert len(runner.calls) == 3
        assert len(client.calls) == 3
        assert statuses[-1] == {"status": "failed", "attempt": 3, "max_attempts": 3,
                                "error": "All generation attempts failed"}

    async def test_script_without_stl_output_is_retried(self, tmp_path):
        runner = FakeRunner(write_stl=False)
        agent, client, _, _ = make_agent([[chunk((fenced(CUBE_CODE), False))]] * 3, runner)

        assert await agent.generate_prototype("A cube", output_dir=str(tmp_path)) is None
        assert len(runner.calls) == 3
        assert "'output.stl' was not found" in client.calls[1]["contents"]

    async def test_answer_without_code_is_never_run(self, tmp_path):
        runner = FakeRunner()
        agent, _, _, _ = make_agent([[chunk(("I cannot help with that.", False))]], runner)

        assert await agent.generate_prototype("A cube", output_dir=str(tmp_path)) is None
        assert runner.calls == []
        assert not (tmp_path / "current_design.py").exists()

    async def test_empty_answer_returns_none(self, tmp_path):
        runner = FakeRunner()
        agent, _, _, _ = make_agent([[chunk(("only thoughts", True))]], runner)

        assert await agent.generate_prototype("A cube", output_dir=str(tmp_path)) is None
        assert runner.calls == []

    async def test_requires_project_output_dir(self):
        agent, client, _, _ = make_agent([])

        with pytest.raises(ServiceError) as raised:
            await agent.generate_prototype("A cube")
        assert raised.value.code == "cad_output_required"
        assert client.calls == []


class TestIteratePrototype:
    async def test_iterates_on_existing_script_with_paths_sanitized(self, tmp_path):
        (tmp_path / "current_design.py").write_text(
            "from build123d import *\nresult_part = Box(10, 10, 10)\n"
            "export_stl(result_part, 'C:\\\\Users\\\\me\\\\cad\\\\output_20250101_000000.stl')\n")
        runner = FakeRunner()
        agent, client, _, _ = make_agent([[chunk((fenced(CUBE_CODE), False))]], runner)

        result = await agent.iterate_prototype("Make it 50% larger", output_dir=str(tmp_path))

        assert base64.b64decode(result["data"]) == STL_BYTES
        prompt = client.calls[0]["contents"]
        assert "User Request: Make it 50% larger" in prompt
        assert "Box(10, 10, 10)" in prompt
        assert "export_stl(result_part, 'output.stl')" in prompt
        assert "C:\\" not in prompt
        assert runner.calls[0]["script_path"] == str(tmp_path / "current_design.py")

    async def test_without_existing_script_falls_back_to_generation(self, tmp_path):
        agent, client, _, _ = make_agent([[chunk((fenced(CUBE_CODE), False))]])

        result = await agent.iterate_prototype("A cube", output_dir=str(tmp_path))

        assert result is not None
        assert "create a 3D model of: A cube" in client.calls[0]["contents"]


@pytest.mark.live_api
class TestLiveCadGeneration:
    """Real Gemini calls that execute AI-written Python. Opt in with JARVIS_LIVE_API_TESTS=1."""

    @pytest.fixture
    def agent(self):
        if not os.getenv("GEMINI_API_KEY"):
            pytest.fail("JARVIS_LIVE_API_TESTS=1 requires a real GEMINI_API_KEY")
        pytest.importorskip("build123d", reason="build123d is needed to run the generated script")
        return CadAgent()

    async def test_generate_simple_cube(self, agent, tmp_path):
        result = await agent.generate_prototype("A simple 10mm cube", output_dir=str(tmp_path))
        assert result is not None
        assert result["format"] == "stl"
        assert os.path.getsize(result["file_path"]) > 0

    async def test_iterate_prototype(self, agent, tmp_path):
        first = await agent.generate_prototype("A sphere with 25mm radius", output_dir=str(tmp_path))
        assert first is not None
        second = await agent.iterate_prototype("Make it 50% larger", output_dir=str(tmp_path))
        assert second is not None
        assert second["file_path"] != first["file_path"]
        assert os.path.getsize(second["file_path"]) > 0
