"""services/wake_word.py: port equivalence, detector rules, listener thread, model files.

Logic tests use fake deterministic "models" (numpy functions with the real shapes) and
never open audio devices or the network; conftest points JARVIS_WAKE_WORD_DIR at an
empty folder. The opt-in live test (JARVIS_LIVE_WAKE_TESTS=1) runs the real models,
named by their real folder, on Windows text-to-speech clips written to a temp dir.
"""

from collections import deque
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import pytest

from services import wake_word
from services.wake_word import (
    Detector,
    FeaturePipeline,
    ModelFile,
    WakeWordError,
    WakeWordListener,
)

np = pytest.importorskip("numpy")

BACKEND = Path(__file__).resolve().parents[1] / "backend"


# --- Fake models -------------------------------------------------------------------------
# Each output row is computed on its own, so results never depend on batch size (BLAS may
# round a batched product differently): framing a long clip at once equals step by step.

_rng = np.random.default_rng(20221)
MEL_WEIGHTS = (_rng.standard_normal((512, 32)) / 4000).astype(np.float32)
EMBED_WEIGHTS = (_rng.standard_normal((76 * 32, 96)) / 30).astype(np.float32)
WAKE_WEIGHTS = (_rng.standard_normal(16 * 96) / 12).astype(np.float32)


class FakeSession:
    def __init__(self, name, function, shape):
        self.name, self.function, self.shape = name, function, shape
        self.calls = 0

    def get_inputs(self):
        return [SimpleNamespace(name=self.name, shape=self.shape)]

    def run(self, outputs, feeds):
        assert outputs is None and list(feeds) == [self.name]
        value = feeds[self.name]
        assert value.dtype == np.float32
        self.calls += 1
        return [self.function(value)]


def fake_mel(x):
    """(batch, samples) -> (time, 1, frames, 32): 512-sample frames every 160 samples."""
    assert x.ndim == 2 and x.shape[0] == 1
    samples = x[0]
    count = (len(samples) - 512) // 160 + 1
    frames = [np.log1p(np.abs(samples[i * 160 : i * 160 + 512] @ MEL_WEIGHTS)) * 4 - 20
              for i in range(count)]
    return np.stack(frames).astype(np.float32)[None, None]


def fake_embedding(x):
    """(N, 76, 32, 1) -> (N, 1, 1, 96)."""
    assert x.shape[1:] == (76, 32, 1)
    rows = [np.tanh(window.reshape(-1) @ EMBED_WEIGHTS) for window in x]
    return np.stack(rows).astype(np.float32)[:, None, None, :]


def fake_wake(x):
    """(1, 16, 96) -> (1, 1) in [0, 1]."""
    assert x.shape == (1, 16, 96)
    value = 1 / (1 + np.exp(-(x.reshape(-1) @ WAKE_WEIGHTS)))
    return np.array([[value]], dtype=np.float32)


def fake_sessions():
    return (FakeSession("input", fake_mel, ["batch_size", "samples"]),
            FakeSession("input_1", fake_embedding, ["n", 76, 32, 1]),
            FakeSession("x.1", fake_wake, [1, 16, 96]))


def fake_pipeline():
    return FeaturePipeline(*fake_sessions())


# --- Reference: a direct transcription of upstream v0.5.1 ---------------------------------


class UpstreamReference:
    """openwakeword AudioFeatures streaming + Model.predict scoring, ONNX branch only."""

    def __init__(self, mel, embedding, wake):
        self.melspec_model_predict = lambda x: mel.run(None, {"input": x})
        self.embedding_model_predict = lambda x: embedding.run(None, {"input_1": x})[0].squeeze()
        self.wake = wake
        self.model_inputs = wake.get_inputs()[0].shape[1]
        self.raw_data_buffer = deque(maxlen=16000 * 10)
        self.melspectrogram_buffer = np.ones((76, 32))
        self.melspectrogram_max_len = 10 * 97
        self.accumulated_samples = 0
        self.raw_data_remainder = np.empty(0)
        self.feature_buffer = self._get_embeddings(
            np.random.randint(-1000, 1000, 16000 * 4).astype(np.int16))
        self.feature_buffer_max_len = 120
        self.prediction_buffer = deque(maxlen=30)

    def _get_melspectrogram(self, x, melspec_transform=lambda x: x / 10 + 2):
        x = np.array(x).astype(np.int16) if isinstance(x, list) else x
        x = x[None,] if len(x.shape) < 2 else x
        x = x.astype(np.float32) if x.dtype != np.float32 else x
        outputs = self.melspec_model_predict(x)
        spec = np.squeeze(outputs[0])
        return melspec_transform(spec)

    def _get_embeddings(self, x, window_size=76):
        spec = self._get_melspectrogram(x)
        windows = []
        for i in range(0, spec.shape[0], 8):
            window = spec[i : i + window_size]
            if window.shape[0] == window_size:
                windows.append(window)
        batch = np.expand_dims(np.array(windows), axis=-1).astype(np.float32)
        return self.embedding_model_predict(batch)

    def _streaming_melspectrogram(self, n_samples):
        self.melspectrogram_buffer = np.vstack((
            self.melspectrogram_buffer,
            self._get_melspectrogram(list(self.raw_data_buffer)[-n_samples - 160 * 3 :]),
        ))
        if self.melspectrogram_buffer.shape[0] > self.melspectrogram_max_len:
            self.melspectrogram_buffer = self.melspectrogram_buffer[-self.melspectrogram_max_len :, :]

    def _buffer_raw_data(self, x):
        self.raw_data_buffer.extend(x.tolist() if isinstance(x, np.ndarray) else x)

    def _streaming_features(self, x):
        processed_samples = 0
        if self.raw_data_remainder.shape[0] != 0:
            x = np.concatenate((self.raw_data_remainder, x))
            self.raw_data_remainder = np.empty(0)
        if self.accumulated_samples + x.shape[0] >= 1280:
            remainder = (self.accumulated_samples + x.shape[0]) % 1280
            if remainder != 0:
                x_even_chunks = x[0:-remainder]
                self._buffer_raw_data(x_even_chunks)
                self.accumulated_samples += len(x_even_chunks)
                self.raw_data_remainder = x[-remainder:]
            else:
                self._buffer_raw_data(x)
                self.accumulated_samples += x.shape[0]
                self.raw_data_remainder = np.empty(0)
        else:
            self.accumulated_samples += x.shape[0]
            self._buffer_raw_data(x)
        if self.accumulated_samples >= 1280 and self.accumulated_samples % 1280 == 0:
            self._streaming_melspectrogram(self.accumulated_samples)
            for i in np.arange(self.accumulated_samples // 1280 - 1, -1, -1):
                ndx = -8 * i
                ndx = ndx if ndx != 0 else len(self.melspectrogram_buffer)
                x = self.melspectrogram_buffer[-76 + ndx : ndx].astype(np.float32)[None, :, :, None]
                if x.shape[1] == 76:
                    self.feature_buffer = np.vstack((self.feature_buffer,
                                                     self.embedding_model_predict(x)))
            processed_samples = self.accumulated_samples
            self.accumulated_samples = 0
        if self.feature_buffer.shape[0] > self.feature_buffer_max_len:
            self.feature_buffer = self.feature_buffer[-self.feature_buffer_max_len :, :]
        return processed_samples if processed_samples != 0 else self.accumulated_samples

    def get_features(self, n_feature_frames=16, start_ndx=-1):
        if start_ndx != -1:
            end_ndx = (start_ndx + int(n_feature_frames)
                       if start_ndx + n_feature_frames != 0 else len(self.feature_buffer))
            return self.feature_buffer[start_ndx:end_ndx, :][None,].astype(np.float32)
        return self.feature_buffer[int(-1 * n_feature_frames) :, :][None,].astype(np.float32)

    def _wake_predict(self, x):
        return self.wake.run(None, {self.wake.get_inputs()[0].name: x})

    def predict(self, x):
        """(score, steps completed by this call); score as upstream returns it."""
        n_prepared_samples = self._streaming_features(x)
        if n_prepared_samples > 1280:
            group_predictions = []
            for i in np.arange(n_prepared_samples // 1280 - 1, -1, -1):
                group_predictions.extend(self._wake_predict(
                    self.get_features(self.model_inputs, start_ndx=-self.model_inputs - i)))
            prediction = np.array(group_predictions).max(axis=0)[None,]
        elif n_prepared_samples == 1280:
            prediction = self._wake_predict(self.get_features(self.model_inputs))
        else:
            prediction = [[[self.prediction_buffer[-1]]]] if len(self.prediction_buffer) else [[[0]]]
        score = prediction[0][0][0]
        if len(self.prediction_buffer) < 5:
            score = 0.0
        self.prediction_buffer.append(score)
        steps = n_prepared_samples // 1280 if n_prepared_samples >= 1280 else 0
        return score, steps


def make_audio(seconds=40, seed=7):
    """Noise, tones and silence: something the fake models score unevenly."""
    rng = np.random.default_rng(seed)
    count = int(seconds * 16000)
    t = np.arange(count) / 16000
    audio = rng.normal(0, 900, count) + 6000 * np.sin(2 * np.pi * 440 * t) * (np.sin(t * 1.3) > 0)
    audio[count // 3 : count // 3 + 8000] = 0
    return np.clip(audio, -32768, 32767).astype(np.int16)


def random_chunks(audio, rng, low=160, high=4000):
    position = 0
    while position < len(audio):
        size = int(rng.integers(low, high + 1))
        yield audio[position : position + size]
        position += size


def test_port_matches_upstream_step_by_step_after_warmup():
    np.random.seed(1)
    audio = make_audio()
    reference = UpstreamReference(*fake_sessions())
    expected = [reference.predict(audio[i : i + 1280])[0]
                for i in range(0, len(audio) - 1279, 1280)]
    for seed in (1, 2, 3):
        pipeline = fake_pipeline()
        rng = np.random.default_rng(seed)
        scores = []
        for chunk in random_chunks(audio, rng):
            scores.extend(pipeline.process(chunk.astype("<i2").tobytes()))
        assert len(scores) == len(expected) == pipeline.steps
        warm = wake_word.WARMUP_STEPS
        assert scores[warm:] == expected[warm:]  # exactly equal, not approximately
        assert 0 <= min(scores) and max(scores) <= 1
        assert max(scores[warm:]) - min(scores[warm:]) > 0.05  # the fake really varies


def test_port_matches_upstream_fed_the_same_random_chunks():
    """Upstream fed multi-step chunks scores the group by its maximum: compare that too."""
    np.random.seed(2)
    audio = make_audio(seconds=30, seed=11)
    reference = UpstreamReference(*fake_sessions())
    pipeline = fake_pipeline()
    rng = np.random.default_rng(5)
    compared = 0
    for chunk in random_chunks(audio, rng):
        score, steps = reference.predict(chunk)
        mine = pipeline.process(chunk.astype("<i2").tobytes())
        assert len(mine) == steps
        if mine and pipeline.steps - len(mine) >= wake_word.WARMUP_STEPS:
            assert max(mine) == score
            compared += 1
    assert compared > 100


def test_reset_restarts_the_stream_exactly():
    audio = make_audio(seconds=8)
    pipeline = fake_pipeline()
    first = pipeline.process(audio.tobytes())
    pipeline.process(make_audio(seconds=3, seed=99).tobytes())
    pipeline.reset()
    assert pipeline.steps == 0 and not pipeline.warm
    assert pipeline.process(audio.tobytes()) == first


def test_odd_byte_chunks_and_bounded_buffers():
    audio = make_audio(seconds=6).tobytes()
    whole = fake_pipeline().process(audio)
    pipeline = fake_pipeline()
    rng = np.random.default_rng(3)
    scores, position = [], 0
    while position < len(audio):
        size = int(rng.integers(1, 999))  # odd byte counts split samples
        scores.extend(pipeline.process(audio[position : position + size]))
        position += size
    assert scores == whole
    assert pipeline._raw.shape == (1760,)
    assert pipeline._mel_frames.shape == (76, 32)
    assert pipeline._features.shape == (16, 96)


def test_each_step_feeds_the_models_the_documented_windows():
    seen = {}
    mel, embedding, wake = fake_sessions()
    for session, key in ((mel, "mel"), (embedding, "embedding"), (wake, "wake")):
        def record(x, function=session.function, key=key):
            seen[key] = x.copy()
            return function(x)
        session.function = record
    pipeline = FeaturePipeline(mel, embedding, wake)
    audio = (np.arange(1280 * 3) % 2000 - 1000).astype(np.int16)
    pipeline.process(audio.tobytes())
    assert seen["mel"].shape == (1, 1760)
    assert seen["mel"].dtype == np.float32
    assert np.array_equal(seen["mel"][0], audio[-1760:].astype(np.float32))  # raw, unscaled
    assert seen["embedding"].shape == (1, 76, 32, 1)
    expected = fake_mel(audio[-1760:].astype(np.float32)[None])[0, 0] / 10 + 2
    assert np.array_equal(seen["embedding"][0, -8:, :, 0], expected)
    assert seen["wake"].shape == (1, 16, 96)
    assert mel.calls == embedding.calls == wake.calls == 3


def test_unexpected_wake_model_shape_is_refused():
    mel, embedding, _ = fake_sessions()
    with pytest.raises(WakeWordError):
        FeaturePipeline(mel, embedding, FakeSession("x.1", fake_wake, [1, 20, 96]))


# --- Detector -----------------------------------------------------------------------------


class ScriptedPipeline:
    """Returns scripted scores: one step per 2560 bytes fed."""

    def __init__(self, scores):
        self.scores = list(scores)
        self.steps = 0
        self.resets = 0

    def reset(self):
        self.steps = 0
        self.resets += 1

    def process(self, pcm):
        out = []
        for _ in range(len(pcm) // 2560):
            out.append(self.scores[self.steps] if self.steps < len(self.scores) else 0.0)
            self.steps += 1
        return out


STEP = bytes(2560)


def run_steps(detector, count):
    found = []
    for _ in range(count):
        if detector.feed(STEP):
            found.append(detector.pipeline.steps)
    return found


@pytest.mark.parametrize("sensitivity,threshold", [("low", 0.7), ("normal", 0.5), ("high", 0.35)])
def test_thresholds_per_sensitivity(sensitivity, threshold):
    below, at = threshold - 0.001, threshold
    scores = [0.0] * 30 + [below] + [0.0] * 30 + [at]
    detector = Detector(ScriptedPipeline(scores), sensitivity)
    assert detector.threshold == threshold
    assert run_steps(detector, len(scores)) == [62]


def test_unknown_sensitivity_is_refused():
    with pytest.raises(ValueError):
        Detector(ScriptedPipeline([]), "extreme")
    detector = Detector(ScriptedPipeline([]))
    with pytest.raises(ValueError):
        detector.sensitivity = "loud"


def test_warmup_suppresses_the_first_two_seconds():
    assert wake_word.WARMUP_STEPS * 1280 == 2 * 16000
    detector = Detector(ScriptedPipeline([1.0] * 27))
    assert run_steps(detector, 27) == [26]


@pytest.mark.parametrize("sensitivity", ["low", "normal", "high"])
def test_audible_raises_threshold_to_at_least_0_7(sensitivity):
    detector = Detector(ScriptedPipeline([]), sensitivity)
    detector.audible = True
    assert detector.threshold == 0.7
    detector.audible = False
    assert detector.threshold == wake_word.THRESHOLDS[sensitivity]


def test_audible_guard_applies_before_refractory_starts():
    scores = [0.0] * 30 + [0.6, 0.6, 0.69, 0.7]
    detector = Detector(ScriptedPipeline(scores), "high")
    detector.audible = True
    assert run_steps(detector, 33) == []  # 0.6 and 0.69 rejected while audible ...
    assert run_steps(detector, 1) == [34]  # ... and they started no refractory period
    pipeline = ScriptedPipeline([0.0] * 30 + [0.6, 0.6])
    detector = Detector(pipeline, "normal")
    detector.audible = True
    assert run_steps(detector, 31) == []
    detector.audible = False
    assert run_steps(detector, 1) == [32]


def test_refractory_period_is_two_seconds_of_audio():
    scores = [0.0] * 30 + [0.9] * 60
    detector = Detector(ScriptedPipeline(scores))
    # Detection at step 31, quiet for 25 steps (2 s), detect again at 57, then 83.
    assert run_steps(detector, 90) == [31, 57, 83]


def test_several_steps_in_one_chunk():
    detector = Detector(ScriptedPipeline([0.0] * 30 + [0.9] * 30))
    assert detector.feed(bytes(2560 * 60)) == [0.9, 0.9]  # steps 31 and 57


def test_reset_restarts_warmup_and_clears_refractory():
    pipeline = ScriptedPipeline([0.0] * 30 + [0.9] * 10)
    detector = Detector(pipeline)
    assert run_steps(detector, 31) == [31]
    pipeline.scores = [0.9] * 40
    detector.reset()
    assert pipeline.resets == 1 and pipeline.steps == 0
    assert run_steps(detector, 30) == [26]


# --- Listener thread ------------------------------------------------------------------------


class GatedPipeline(ScriptedPipeline):
    """Blocks inside process() until released, to fill the queue deterministically."""

    def __init__(self, scores):
        super().__init__(scores)
        self.entered = threading.Event()
        self.gate = threading.Event()
        self.fed = []

    def process(self, pcm):
        self.entered.set()
        assert self.gate.wait(5)
        self.fed.append(bytes(pcm))
        return super().process(pcm)


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def test_listener_detects_on_its_own_thread():
    calls = []
    pipeline = ScriptedPipeline([0.0] * 30 + [0.95])
    listener = WakeWordListener(lambda score, at: calls.append(
        (score, at, threading.current_thread().name)), pipeline_factory=lambda: pipeline,
        clock=lambda: 123.5)
    assert listener.submit(STEP) is False  # not running: nothing is queued
    assert listener.start() is True
    try:
        assert wait_for(lambda: listener.state == "listening")
        for _ in range(31):
            assert listener.submit(STEP)
        assert wait_for(lambda: calls)
    finally:
        assert listener.stop() is True
    assert calls == [(0.95, 123.5, "jarvis-wake-word")]
    assert listener.state == "stopped"


def test_listener_start_stop_idempotent_and_reuses_models():
    built = []

    def factory():
        built.append(ScriptedPipeline([]))
        return built[-1]

    listener = WakeWordListener(lambda *_: None, pipeline_factory=factory)
    assert listener.stop() is True  # never started
    assert listener.start() is True
    assert listener.start() is False
    thread = listener._thread
    assert wait_for(lambda: listener.state == "listening")
    assert listener.stop(timeout=2) is True and listener.stop() is True
    assert not thread.is_alive() and not listener.running
    assert listener.start() is True
    assert wait_for(lambda: listener.state == "listening")
    assert listener.stop() is True
    assert len(built) == 1  # loaded once, kept across stop/start
    assert built[0].resets == 2  # each start resets: the warmup applies again


def test_stop_from_the_callback_does_not_join_itself():
    results = []
    pipeline = ScriptedPipeline([0.0] * 30 + [0.9])
    listener = WakeWordListener(lambda *_: results.append(listener.stop()),
                                pipeline_factory=lambda: pipeline)
    listener.start()
    thread = listener._thread
    assert wait_for(lambda: listener.state == "listening")
    for _ in range(31):
        listener.submit(STEP)
    assert wait_for(lambda: results == [False] and not thread.is_alive())
    assert listener.state == "stopped" and listener.stop() is True


def test_listener_overflow_drops_oldest_and_counts():
    pipeline = GatedPipeline([])
    listener = WakeWordListener(lambda *_: None, max_chunks=4, pipeline_factory=lambda: pipeline)
    listener.start()
    try:
        assert wait_for(lambda: listener.state == "listening")
        listener.submit(b"\x00\x00first")
        assert pipeline.entered.wait(5)  # the thread holds chunk 1 inside process()
        chunks = [bytes([n]) * 2 for n in range(7)]
        for chunk in chunks:
            listener.submit(chunk)
        assert listener.dropped == 3
        pipeline.gate.set()
        assert wait_for(lambda: len(pipeline.fed) == 5)
        assert pipeline.fed[1:] == chunks[3:]  # the oldest were dropped
    finally:
        pipeline.gate.set()
        listener.stop()


def test_listener_audible_and_sensitivity_reach_the_detector():
    calls = []
    pipeline = ScriptedPipeline([0.0] * 30 + [0.6, 0.6])
    listener = WakeWordListener(lambda score, _at: calls.append(score),
                                pipeline_factory=lambda: pipeline)
    listener.start()
    try:
        assert wait_for(lambda: listener.state == "listening")
        listener.audible = True
        for _ in range(31):
            listener.submit(STEP)
        assert wait_for(lambda: pipeline.steps == 31)
        assert calls == []
        listener.audible = False
        listener.sensitivity = "high"
        listener.submit(STEP)
        assert wait_for(lambda: calls == [0.6])
    finally:
        listener.stop()
    with pytest.raises(ValueError):
        listener.sensitivity = "max"


def test_listener_reset_restarts_warmup():
    pipeline = ScriptedPipeline([0.9] * 100)
    calls = []
    listener = WakeWordListener(lambda score, _at: calls.append(score),
                                pipeline_factory=lambda: pipeline)
    listener.start()
    try:
        assert wait_for(lambda: listener.state == "listening")
        for _ in range(20):
            listener.submit(STEP)
        assert wait_for(lambda: pipeline.steps == 20)
        listener.reset()
        assert wait_for(lambda: pipeline.resets == 2)  # one at start, one requested
        for _ in range(25):
            listener.submit(STEP)
        assert wait_for(lambda: pipeline.steps == 25)
        assert calls == []
    finally:
        listener.stop()


def test_listener_reports_load_errors_and_callback_errors(caplog):
    caplog.set_level(logging.INFO, logger="jarvis.wake_word")
    listener = WakeWordListener(lambda *_: None, pipeline_factory=lambda: (_ for _ in ()).throw(
        WakeWordError(wake_word.MISSING_REASON, "missing")))
    listener.start()
    assert wait_for(lambda: listener.state == "error")
    assert listener.error == wake_word.MISSING_REASON
    assert wait_for(lambda: not listener.running)
    assert listener.submit(STEP) is False  # nothing queues behind a failed start
    listener.stop()

    def broken(*_):
        raise RuntimeError("boom")

    pipeline = ScriptedPipeline([0.0] * 30 + [0.9, 0.0, 0.0])
    listener = WakeWordListener(broken, pipeline_factory=lambda: pipeline)
    listener.start()
    try:
        for _ in range(33):
            assert wait_for(lambda: listener.state == "listening")
            listener.submit(STEP)
        assert wait_for(lambda: pipeline.steps == 33)  # still running after the failure
        assert listener.state == "listening"
    finally:
        listener.stop()
    assert "Wake-word callback failed (RuntimeError)." in caplog.text
    assert "Wake phrase heard (score 0.90)." in caplog.text


def test_default_listener_without_models_reports_why():
    """The conftest folder is empty: the real loader refuses before importing onnxruntime."""
    listener = WakeWordListener(lambda *_: None)
    listener.start()
    assert wait_for(lambda: listener.state == "error")
    listener.stop()
    assert listener.error == wake_word.MISSING_REASON


# --- Model files and status ---------------------------------------------------------------


def write_models(folder, contents=None):
    contents = contents or {"mel": b"mel-model" * 10, "embedding": b"embedding" * 12,
                            "wake": b"hey-jarvis" * 9}
    manifest = []
    for role, data in contents.items():
        (folder / f"{role}.onnx").write_bytes(data)
        manifest.append(ModelFile(role, f"{role}.onnx", len(data),
                                  hashlib.sha256(data).hexdigest(), f"https://example.test/{role}"))
    return tuple(manifest), contents


def test_conftest_points_at_an_empty_model_folder():
    folder = wake_word.model_directory()
    assert folder == Path(os.environ["JARVIS_WAKE_WORD_DIR"]).resolve()
    assert list(folder.iterdir()) == []
    assert wake_word.status()["models"] == "missing"


def test_default_folder_is_under_the_jarvis_product_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_WAKE_WORD_DIR", "")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert wake_word.model_directory() == tmp_path / "JARVIS" / "models" / "wake-word"
    monkeypatch.delenv("LOCALAPPDATA")
    with pytest.raises(WakeWordError):
        wake_word.model_directory()
    assert wake_word.status()["available"] is False


def test_manifest_pins_the_v0_5_1_release():
    assert [item.file for item in wake_word.MANIFEST] == [
        "melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"]
    for item in wake_word.MANIFEST:
        assert item.url == ("https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
                            + item.file)
        assert len(item.sha256) == 64 and item.bytes > 1_000_000


def test_verified_files_load_and_status_is_available(tmp_path):
    manifest, contents = write_models(tmp_path)
    assert wake_word.read_verified(tmp_path, manifest) == contents
    state = wake_word.status(tmp_path, manifest)
    assert state == {"installed": True, "models": "ok", "available": True, "reason": None}


def test_missing_file_cannot_load(tmp_path):
    manifest, _ = write_models(tmp_path)
    (tmp_path / "wake.onnx").unlink()
    with pytest.raises(WakeWordError) as error:
        wake_word.read_verified(tmp_path, manifest)
    assert error.value.kind == "missing"
    state = wake_word.status(tmp_path, manifest)
    assert state["models"] == "missing" and state["available"] is False
    assert state["reason"] == wake_word.MISSING_REASON
    assert "missing" in state["reason"] and "fetch-wake-word-models.py" in state["reason"]


def test_wrong_size_cannot_load(tmp_path):
    manifest, contents = write_models(tmp_path)
    (tmp_path / "mel.onnx").write_bytes(contents["mel"] + b"x")
    with pytest.raises(WakeWordError) as error:
        wake_word.read_verified(tmp_path, manifest)
    assert error.value.kind == "changed"
    state = wake_word.status(tmp_path, manifest)
    assert state["models"] == "changed" and "changed" in state["reason"]


def test_wrong_hash_cannot_load(tmp_path):
    manifest, contents = write_models(tmp_path)
    data = bytearray(contents["embedding"])
    data[3] ^= 1
    (tmp_path / "embedding.onnx").write_bytes(bytes(data))
    with pytest.raises(WakeWordError) as error:
        wake_word.read_verified(tmp_path, manifest)
    assert error.value.kind == "changed"
    assert wake_word.status(tmp_path, manifest)["models"] == "changed"


def test_file_swapped_after_the_check_cannot_load(tmp_path):
    manifest, contents = write_models(tmp_path)
    path = tmp_path / "wake.onnx"
    assert wake_word.status(tmp_path, manifest)["available"] is True
    stat = path.stat()
    swapped = bytes(reversed(contents["wake"]))
    path.write_bytes(swapped)  # same size; keep the mtime so the status cache still hits
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert wake_word.status(tmp_path, manifest)["available"] is True  # cached by design
    with pytest.raises(WakeWordError):  # but loading always re-hashes what it reads
        wake_word.read_verified(tmp_path, manifest)


def test_status_rehashes_when_size_or_mtime_changes(tmp_path):
    manifest, contents = write_models(tmp_path)
    assert wake_word.status(tmp_path, manifest)["models"] == "ok"
    path = tmp_path / "mel.onnx"
    path.write_bytes(bytes(reversed(contents["mel"])))
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10_000_000))
    assert wake_word.status(tmp_path, manifest)["models"] == "changed"


def test_status_without_extras_names_the_install_command(monkeypatch, tmp_path):
    manifest, _ = write_models(tmp_path)
    real = wake_word.importlib.util.find_spec
    monkeypatch.setattr(wake_word.importlib.util, "find_spec",
                        lambda name, *a: None if name == "onnxruntime" else real(name, *a))
    state = wake_word.status(tmp_path, manifest)
    assert state["installed"] is False and state["available"] is False
    assert "requirements-wake.txt" in state["reason"]


class FakeOrt(ModuleType):
    """Stands in for onnxruntime: records how sessions are built."""

    class ExecutionMode:
        ORT_SEQUENTIAL = "sequential"
        ORT_PARALLEL = "parallel"

    def __init__(self):
        super().__init__("onnxruntime")
        self.events = []
        ort = self

        class SessionOptions:
            pass

        class InferenceSession:
            def __init__(self, model, sess_options=None, providers=None):
                ort.events.append(("session", model, sess_options, providers))
                self.fake = {b"m": fake_sessions()[0], b"e": fake_sessions()[1],
                             b"w": fake_sessions()[2]}[model[:1]]

            def get_inputs(self):
                return self.fake.get_inputs()

            def run(self, outputs, feeds):
                return self.fake.run(outputs, feeds)

        self.SessionOptions = SessionOptions
        self.InferenceSession = InferenceSession

    def disable_telemetry_events(self):
        self.events.append(("telemetry-off",))


def test_sessions_come_from_the_verified_bytes_cpu_only(monkeypatch, tmp_path):
    manifest, contents = write_models(tmp_path, {"mel": b"m" * 50, "embedding": b"e" * 60,
                                                 "wake": b"w" * 70})
    ort = FakeOrt()
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    pipeline = wake_word.load_pipeline(tmp_path, manifest)
    assert ort.events[0] == ("telemetry-off",)
    sessions = ort.events[1:]
    assert [event[1] for event in sessions] == list(contents.values())  # the hashed bytes
    for _, model, options, providers in sessions:
        assert isinstance(model, bytes)
        assert providers == ["CPUExecutionProvider"]
        assert options.intra_op_num_threads == 1 and options.inter_op_num_threads == 1
        assert options.execution_mode == "sequential"
        assert options.log_severity_level == 3
    assert len(pipeline.process(bytes(2560 * 2))) == 2


def run_isolated(code, tmp_path):
    env = dict(os.environ, JARVIS_WAKE_WORD_DIR=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_import_and_status_never_import_numpy_or_onnxruntime(tmp_path):
    manifest, _ = write_models(tmp_path)
    code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "import services.wake_word as w\n"
        "loaded = [m for m in ('numpy', 'onnxruntime') if m in sys.modules]\n"
        "s1 = w.status()\n"
        f"manifest = {[tuple(vars(item).values()) for item in manifest]!r}\n"
        "s2 = w.status(manifest=tuple(w.ModelFile(*m) for m in manifest))\n"
        "loaded += [m for m in ('numpy', 'onnxruntime') if m in sys.modules]\n"
        "print(json.dumps({'loaded': loaded, 'missing': s1['models'], 'ok': s2['models']}))\n"
    )
    assert run_isolated(code, tmp_path) == {"loaded": [], "missing": "missing", "ok": "ok"}


# --- Live: real models on Windows text-to-speech (opt-in) ---------------------------------

SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$jobs = Get-Content -Raw -LiteralPath $args[0] | ConvertFrom-Json
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
if ($jobs.Count -eq 0) {
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'en*' } |
        ForEach-Object { $_.VoiceInfo.Name }
    $s.Dispose()
    exit 0
}
foreach ($job in $jobs) {
    $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $s.SelectVoice($job.voice)
    $s.Rate = [int]$job.rate
    $s.SetOutputToWaveFile($job.path, $format)
    $s.Speak($job.text)
    $s.SetOutputToNull()
    $s.Dispose()
}
"""

POSITIVE = "Hey Jarvis"
NEGATIVES = ("Hey Travis", "Hello there", "Hey Siri", "What's the weather like")
RATES = (0, 3)


def sapi(work, jobs):
    script, spec = work / "sapi.ps1", work / "jobs.json"
    script.write_text(SAPI_SCRIPT, encoding="utf-8")
    spec.write_text(json.dumps(jobs), encoding="utf-8")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), str(spec)],
        capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


def read_wave(path):
    import wave

    with wave.open(str(path), "rb") as clip:
        assert (clip.getframerate(), clip.getsampwidth(), clip.getnchannels()) == (16000, 2, 1)
        return np.frombuffer(clip.readframes(clip.getnframes()), dtype="<i2")


def padded(samples):
    return np.concatenate((np.zeros(40000, np.int16), samples, np.zeros(16000, np.int16)))


def clip_scores(detector, samples, chunk=320):
    """(max score after warmup, detections) for one clip fed in 20 ms chunks."""
    detector.reset()
    pipeline = detector.pipeline
    best, detections = 0.0, []
    original = pipeline.process

    def spy(pcm):
        scores = original(pcm)
        start = pipeline.steps - len(scores) + 1
        nonlocal best
        best = max([best] + [s for i, s in enumerate(scores, start) if i > wake_word.WARMUP_STEPS])
        return scores

    pipeline.process = spy
    try:
        data = samples.astype("<i2").tobytes()
        for i in range(0, len(data), chunk * 2):
            detections += detector.feed(data[i : i + chunk * 2])
    finally:
        del pipeline.process
    return best, detections


@pytest.mark.live_wake
@pytest.mark.skipif(sys.platform != "win32", reason="uses Windows SAPI text-to-speech")
def test_live_hey_jarvis_on_windows_speech(tmp_path):
    from services.data_migration import product_folder

    real_folder = product_folder(Path(os.environ["LOCALAPPDATA"])) / "models" / "wake-word"
    pipeline = wake_word.load_pipeline(real_folder)  # explicit path, not the conftest override
    detector = Detector(pipeline, "normal")

    voices = [line.strip() for line in sapi(tmp_path, []).splitlines() if line.strip()]
    assert voices, "no English SAPI voices installed"
    jobs, labels = [], []
    for voice in voices:
        for rate in RATES:
            jobs.append({"voice": voice, "rate": rate, "text": POSITIVE,
                         "path": str(tmp_path / f"pos-{len(jobs)}.wav")})
            labels.append((True, f"{POSITIVE!r} / {voice} / rate {rate}"))
        for text in NEGATIVES:
            jobs.append({"voice": voice, "rate": 0, "text": text,
                         "path": str(tmp_path / f"neg-{len(jobs)}.wav")})
            labels.append((False, f"{text!r} / {voice} / rate 0"))
    sapi(tmp_path, jobs)
    clips = [(positive, label, padded(read_wave(job["path"])))
             for (positive, label), job in zip(labels, jobs, strict=True)]
    clips.append((False, "silence (3 s)", padded(np.zeros(48000, np.int16))))
    rng = np.random.default_rng(30)
    noise = np.clip(rng.normal(0, 32768 * 10 ** (-30 / 20), 48000), -32768, 32767)
    clips.append((False, "white noise -30 dBFS (3 s)", padded(noise.astype(np.int16))))

    failures = []
    print()
    for positive, label, samples in clips:
        best, detections = clip_scores(detector, samples)
        print(f"  {'+' if positive else '-'} max {best:.4f}  detections {len(detections)}  {label}")
        if positive != bool(detections):
            failures.append(label)

    # CPU: thread time per second of audio over 60 s, models already loaded.
    speech = np.concatenate([samples for _, _, samples in clips])
    audio = np.resize(speech, 60 * 16000).astype("<i2").tobytes()
    detector.reset()
    started = time.thread_time()
    for i in range(0, len(audio), 640):
        detector.feed(audio[i : i + 640])
    cpu = (time.thread_time() - started) / 60
    print(f"  CPU: {cpu * 1000:.2f} ms per second of audio = {cpu * 100:.2f}% of one core "
          f"(target < 3%)")
    assert not failures, f"misclassified: {failures}"
    assert cpu < 0.03
