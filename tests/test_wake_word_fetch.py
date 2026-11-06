"""scripts/fetch-wake-word-models.py with a fake opener: never touches the network."""

import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

from services.wake_word import MANIFEST, ModelFile

spec = importlib.util.spec_from_file_location(
    "fetch_wake_word_models",
    Path(__file__).resolve().parents[1] / "scripts/fetch-wake-word-models.py",
)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)

FILES = {"one.onnx": b"first model " * 400, "two.onnx": b"second model " * 300}


def manifest(files=FILES):
    return tuple(ModelFile(name.split(".")[0], name, len(data), hashlib.sha256(data).hexdigest(),
                           f"https://example.test/{name}") for name, data in files.items())


class FakeOpener:
    """Serves bytes by URL (optionally altered) and records every request."""

    def __init__(self, served):
        self.served = served
        self.urls = []

    def open(self, url, timeout=None):
        assert timeout
        self.urls.append(url)
        return io.BytesIO(self.served[url.rsplit("/", 1)[1]])


def run(folder, opener, check_only=False, files=FILES):
    lines = []
    code = fetch.run(folder, manifest(files), opener=opener, check_only=check_only,
                     out=lines.append)
    return code, "\n".join(lines)


def leftovers(folder):
    return sorted(path.name for path in folder.iterdir() if path.name.endswith(".part"))


def test_good_files_are_fetched_verified_and_kept(tmp_path):
    opener = FakeOpener(FILES)
    code, output = run(tmp_path / "models", opener)
    assert code == 0
    for name, data in FILES.items():
        assert (tmp_path / "models" / name).read_bytes() == data
    assert leftovers(tmp_path / "models") == []
    assert "CC BY-NC-SA 4.0" in output and "non-commercial" in output
    # A second run finds them verified and downloads nothing.
    again = FakeOpener({})
    assert run(tmp_path / "models", again)[0] == 0
    assert again.urls == []


def test_wrong_size_is_deleted_and_fails(tmp_path):
    served = dict(FILES, **{"two.onnx": FILES["two.onnx"] + b"!"})
    code, output = run(tmp_path, FakeOpener(served))
    assert code == 1
    assert (tmp_path / "one.onnx").exists()
    assert not (tmp_path / "two.onnx").exists()
    assert leftovers(tmp_path) == []
    assert "two.onnx: FAILED" in output and "larger than" in output
    short = dict(FILES, **{"one.onnx": FILES["one.onnx"][:-1]})
    code, output = run(tmp_path / "short", FakeOpener(short))
    assert code == 1 and not (tmp_path / "short" / "one.onnx").exists()
    assert leftovers(tmp_path / "short") == []


def test_wrong_hash_is_deleted_and_fails(tmp_path):
    altered = bytearray(FILES["one.onnx"])
    altered[10] ^= 0x20
    code, output = run(tmp_path, FakeOpener(dict(FILES, **{"one.onnx": bytes(altered)})))
    assert code == 1
    assert not (tmp_path / "one.onnx").exists()
    assert (tmp_path / "two.onnx").read_bytes() == FILES["two.onnx"]
    assert leftovers(tmp_path) == []
    assert "SHA-256" in output


def test_a_bad_download_never_replaces_a_file_in_place(tmp_path):
    (tmp_path / "one.onnx").write_bytes(b"stale")
    served = dict(FILES, **{"one.onnx": b"x" * len(FILES["one.onnx"])})
    assert run(tmp_path, FakeOpener(served))[0] == 1
    assert (tmp_path / "one.onnx").read_bytes() == b"stale"  # the rename never happened


def test_check_only_verifies_and_never_downloads(tmp_path):
    class NoNetwork:
        def open(self, *_args, **_kwargs):
            raise AssertionError("--check must not download")

    code, output = run(tmp_path, NoNetwork(), check_only=True)
    assert code == 1 and "one.onnx: missing or changed" in output
    for name, data in FILES.items():
        (tmp_path / name).write_bytes(data)
    assert run(tmp_path, NoNetwork(), check_only=True)[0] == 0
    (tmp_path / "two.onnx").write_bytes(FILES["two.onnx"][::-1])
    code, output = run(tmp_path, NoNetwork(), check_only=True)
    assert code == 1 and "two.onnx: missing or changed" in output and "one.onnx: ok" in output


def test_cli_check_uses_the_configured_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_WAKE_WORD_DIR", str(tmp_path))
    assert fetch.main(["--check"]) == 1  # the real manifest: nothing there
    output = capsys.readouterr().out
    assert str(tmp_path.resolve()) in output
    assert all(f"{item.file}: missing or changed" in output for item in MANIFEST)
    assert fetch.main(["--check", "--dir", str(tmp_path / "other")]) == 1


def test_non_https_sources_are_refused(tmp_path):
    item = ModelFile("x", "x.onnx", 1, "0" * 64, "http://example.test/x.onnx")
    with pytest.raises(fetch.FetchError):
        fetch.fetch_one(FakeOpener({"x.onnx": b"x"}), item, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_default_opener_verifies_with_truststore():
    opener = fetch.default_opener()
    handlers = [h for h in opener.handlers if type(h).__name__ == "HTTPSHandler"]
    assert handlers and type(handlers[0]._context).__module__.startswith("truststore")
