# Copyright 2022 David Scripka. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this
# file except in compliance with the License. A copy is in LICENSES/Apache-2.0.txt at the
# root of this repository, or at http://www.apache.org/licenses/LICENSE-2.0. Unless
# required by applicable law or agreed to in writing, software distributed under the
# License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the License for the specific language governing
# permissions and limitations under the License.
#
# Modified port for JARVIS: this file is not the original openWakeWord code. It ports the
# streaming feature pipeline of ``AudioFeatures`` (openwakeword/utils.py) and the scoring
# part of ``Model.predict`` (openwakeword/model.py) from openWakeWord tag v0.5.1, rewritten
# around fixed-size numpy buffers, with tflite, Speex, VAD, custom verifiers, training
# code and the buffer seeding removed, and with JARVIS's own model checks, detector and
# listener thread added.
"""Local "Hey Jarvis" wake-phrase detection (openWakeWord v0.5.1 models, ONNX on the CPU).

Everything here runs on this PC: microphone audio is scored by three small ONNX models
and nothing leaves the machine until the phrase is heard (J3b wires the result into the
microphone, tray and Preferences). Audio and per-frame scores are never logged or
stored; only state changes and the score of an accepted detection are logged.

Pipeline (exactly upstream's, one 80 ms step at a time). Input is 16 kHz mono PCM16
little-endian in chunks of any size; samples are gathered into 1280-sample steps and the
remainder carries over to the next chunk. Per step:

1. the mel model gets the last 1280 + 480 samples as float32 of the raw int16 values and
   returns 8 frames of 32 mel bins, transformed by ``x / 10 + 2``;
2. the embedding model gets the last 76 mel frames, shaped (1, 76, 32, 1), and returns
   one 96-value embedding;
3. the wake model gets the last 16 embeddings, shaped (1, 16, 96), and returns a score
   in [0, 1].

Upstream seeds its buffers (mel frames of ones, embeddings of random noise) and zeroes
its first 5 predictions. This port seeds them with zeros and ones instead and reports
no detection until 2 s of audio (25 steps) has been processed after a start or
``reset()``: by then every input of the wake model comes from real audio, so later
scores equal upstream's for the same audio. (Upstream fed several steps in one call
computes their mel frames in one batch, which differs from step-by-step in the last
float32 bits only.)

Model files are pinned in ``MANIFEST`` (size and SHA-256); the folder is
``JARVIS_WAKE_WORD_DIR``, else ``%LOCALAPPDATA%\\JARVIS\\models\\wake-word``. The models
are CC BY-NC-SA 4.0 (personal, non-commercial use) and are never committed or packaged;
``scripts/fetch-wake-word-models.py`` fetches them. See docs/WAKE_WORD.md.

numpy and onnxruntime are optional (requirements-wake.txt) and are imported only on the
listener thread (or by whoever builds a pipeline), never when this module is imported;
``status()`` never imports them.
"""

from collections import deque
from dataclasses import dataclass
import hashlib
import importlib.util
import logging
import os
from pathlib import Path
import threading
import time

SAMPLE_RATE = 16000
STEP_SAMPLES = 1280  # 80 ms
MEL_CONTEXT_SAMPLES = 160 * 3  # extra history the mel model needs for a full step
MEL_BINS = 32
EMBEDDING_WINDOW = 76  # mel frames per embedding
EMBEDDING_SIZE = 96
FEATURE_FRAMES = 16  # embeddings per wake-model input
STEP_SECONDS = STEP_SAMPLES / SAMPLE_RATE
WARMUP_SECONDS = 2.0
WARMUP_STEPS = round(WARMUP_SECONDS / STEP_SECONDS)  # 25
REFRACTORY_SECONDS = 2.0
REFRACTORY_STEPS = round(REFRACTORY_SECONDS / STEP_SECONDS)  # 25
THRESHOLDS = {"low": 0.7, "normal": 0.5, "high": 0.35}
AUDIBLE_THRESHOLD = 0.7  # floor while JARVIS itself is speaking
DEFAULT_QUEUE_CHUNKS = 64

EXTRAS = ("onnxruntime", "numpy")
EXTRAS_COMMAND = r".\.venv\Scripts\python.exe -m pip install -r requirements-wake.txt"
FETCH_COMMAND = r".\.venv\Scripts\python.exe scripts\fetch-wake-word-models.py"
RELEASE_URL = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
MODEL_LICENCE = (
    'The "Hey Jarvis" models are openWakeWord v0.5.1 pre-trained models, licensed '
    "CC BY-NC-SA 4.0: personal, non-commercial use only. They are never shipped with JARVIS."
)

_logger = logging.getLogger("jarvis.wake_word")


@dataclass(frozen=True)
class ModelFile:
    role: str  # "mel", "embedding" or "wake"
    file: str
    bytes: int
    sha256: str
    url: str


MANIFEST = (
    ModelFile(
        "mel", "melspectrogram.onnx", 1087958,
        "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
        RELEASE_URL + "melspectrogram.onnx",
    ),
    ModelFile(
        "embedding", "embedding_model.onnx", 1326578,
        "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
        RELEASE_URL + "embedding_model.onnx",
    ),
    ModelFile(
        "wake", "hey_jarvis_v0.1.onnx", 1271370,
        "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
        RELEASE_URL + "hey_jarvis_v0.1.onnx",
    ),
)

MISSING_REASON = (
    f'The "Hey Jarvis" model files are missing. Fetch them with {FETCH_COMMAND}.'
)
CHANGED_REASON = (
    f'The "Hey Jarvis" model files have changed. Fetch them again with {FETCH_COMMAND}.'
)
EXTRAS_REASON = f"Install the wake-word extras with {EXTRAS_COMMAND}."


class WakeWordError(Exception):
    """The detector cannot run; ``str()`` is a plain reason, ``kind`` a short code."""

    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.kind = kind


# --- Model files -----------------------------------------------------------------------


def model_directory():
    """JARVIS_WAKE_WORD_DIR, else %LOCALAPPDATA%/JARVIS/models/wake-word."""
    from services import env

    override = env.getenv("WAKE_WORD_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = os.getenv("LOCALAPPDATA")
    if not local:
        raise WakeWordError("Set JARVIS_WAKE_WORD_DIR to the wake-word model folder.", "config")
    from services.data_migration import product_folder

    return product_folder(Path(local)) / "models" / "wake-word"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_verified(directory, manifest=MANIFEST):
    """{role: bytes} for every pinned file, checked by size and then by SHA-256.

    The bytes returned are the bytes that were hashed: callers build the sessions from
    them, so nothing is re-read between the check and the load.
    """
    directory = Path(directory)
    blobs = {}
    for item in manifest:
        path = directory / item.file
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            raise WakeWordError(MISSING_REASON, "missing") from None
        if size != item.bytes:
            raise WakeWordError(CHANGED_REASON, "changed")
        with open(path, "rb") as handle:
            data = handle.read(item.bytes + 1)
        if len(data) != item.bytes or _sha256(data) != item.sha256:
            raise WakeWordError(CHANGED_REASON, "changed")
        blobs[item.role] = data
    return blobs


_status_lock = threading.Lock()
_status_cache = {}  # str(path) -> ((size, mtime_ns), sha256 matched)


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _files_state(directory, manifest):
    """"ok", "missing" or "changed"; hashes are cached by (size, mtime_ns)."""
    for item in manifest:
        path = Path(directory) / item.file
        try:
            stat = path.stat()
        except OSError:
            return "missing"
        if stat.st_size != item.bytes:
            return "changed"
        key, signature = str(path), (stat.st_size, stat.st_mtime_ns)
        with _status_lock:
            cached = _status_cache.get(key)
        if cached is not None and cached[0] == signature:
            matched = cached[1]
        else:
            try:
                matched = _hash_file(path) == item.sha256
            except OSError:
                return "missing"
            with _status_lock:
                _status_cache[key] = (signature, matched)
        if not matched:
            return "changed"
    return "ok"


def status(directory=None, manifest=MANIFEST):
    """Capability view: {"installed", "models", "available", "reason"}; imports nothing heavy.

    ``installed``: numpy and onnxruntime can be imported (checked with find_spec only);
    ``models``: "ok", "missing", "changed" or "unknown"; ``available``: both are fine;
    ``reason``: a plain sentence when not available, else None.
    """
    installed = all(importlib.util.find_spec(name) is not None for name in EXTRAS)
    try:
        folder = Path(directory) if directory is not None else model_directory()
    except WakeWordError as exc:
        return {"installed": installed, "models": "unknown", "available": False,
                "reason": str(exc)}
    models = _files_state(folder, manifest)
    if not installed:
        reason = EXTRAS_REASON
    elif models == "missing":
        reason = MISSING_REASON
    elif models == "changed":
        reason = CHANGED_REASON
    else:
        reason = None
    return {"installed": installed, "models": models, "available": reason is None,
            "reason": reason}


def _onnx_sessions(blobs):
    """CPU-only, single-threaded, sequential sessions built from in-memory model bytes."""
    try:
        import onnxruntime
    except ImportError:
        raise WakeWordError(EXTRAS_REASON, "extras") from None
    onnxruntime.disable_telemetry_events()
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    options.log_severity_level = 3  # errors only
    return {
        role: onnxruntime.InferenceSession(data, sess_options=options,
                                           providers=["CPUExecutionProvider"])
        for role, data in blobs.items()
    }


def load_pipeline(directory=None, manifest=MANIFEST):
    """A ``FeaturePipeline`` on the verified model files (imports numpy and onnxruntime)."""
    folder = Path(directory) if directory is not None else model_directory()
    sessions = _onnx_sessions(read_verified(folder, manifest))
    return FeaturePipeline(sessions["mel"], sessions["embedding"], sessions["wake"])


# --- Streaming features and scores -------------------------------------------------------


class FeaturePipeline:
    """openWakeWord's streaming features and wake score, one 80 ms step at a time.

    ``process(pcm)`` returns the score of every step the chunk completed (often none).
    All buffers are fixed-size numpy arrays. Not thread-safe: one thread feeds it.
    """

    def __init__(self, mel_session, embedding_session, wake_session):
        try:
            import numpy
        except ImportError:
            raise WakeWordError(EXTRAS_REASON, "extras") from None
        self._np = numpy
        self._mel = mel_session
        self._embedding = embedding_session
        self._wake = wake_session
        wake_input = wake_session.get_inputs()[0]
        shape = list(wake_input.shape)
        if len(shape) != 3 or shape[1:] != [FEATURE_FRAMES, EMBEDDING_SIZE]:
            raise WakeWordError("The wake-word model has an unexpected input shape.", "changed")
        self._wake_input = wake_input.name
        self.reset()

    def reset(self):
        np = self._np
        self._raw = np.zeros(STEP_SAMPLES + MEL_CONTEXT_SAMPLES, dtype=np.int16)
        self._pending = np.zeros(STEP_SAMPLES, dtype=np.int16)
        self._pending_count = 0
        self._odd_byte = b""
        self._mel_frames = np.ones((EMBEDDING_WINDOW, MEL_BINS), dtype=np.float32)
        self._features = np.zeros((FEATURE_FRAMES, EMBEDDING_SIZE), dtype=np.float32)
        self.steps = 0  # steps processed since the last reset

    @property
    def warm(self):
        return self.steps > WARMUP_STEPS

    def process(self, pcm):
        np = self._np
        data = bytes(pcm)
        if self._odd_byte:
            data = self._odd_byte + data
        if len(data) % 2:
            self._odd_byte, data = data[-1:], data[:-1]
        else:
            self._odd_byte = b""
        samples = np.frombuffer(data, dtype="<i2")
        scores = []
        offset, total = 0, len(samples)
        while offset < total:
            count = self._pending_count
            take = min(STEP_SAMPLES - count, total - offset)
            self._pending[count:count + take] = samples[offset:offset + take]
            offset += take
            self._pending_count = count + take
            if self._pending_count == STEP_SAMPLES:
                self._pending_count = 0
                scores.append(self._step())
        return scores

    def _step(self):
        np = self._np
        raw = self._raw
        raw[:MEL_CONTEXT_SAMPLES] = raw[STEP_SAMPLES:]
        raw[MEL_CONTEXT_SAMPLES:] = self._pending

        # Mel frames: float32 of the raw int16 values; upstream's transform x/10 + 2.
        outputs = self._mel.run(None, {"input": raw.astype(np.float32)[None, :]})
        spec = np.squeeze(outputs[0])
        spec = spec / 10 + 2
        spec = spec.reshape(-1, MEL_BINS)
        frames = self._mel_frames
        count = spec.shape[0]
        if count >= EMBEDDING_WINDOW:
            frames[:] = spec[-EMBEDDING_WINDOW:]
        elif count:
            frames[:-count] = frames[count:]
            frames[-count:] = spec

        # One embedding from the last 76 mel frames.
        window = frames.astype(np.float32)[None, :, :, None]
        embedding = np.squeeze(self._embedding.run(None, {"input_1": window})[0])
        features = self._features
        features[:-1] = features[1:]
        features[-1] = embedding

        # Wake score from the last 16 embeddings.
        prediction = self._wake.run(None, {self._wake_input: features.astype(np.float32)[None]})
        self.steps += 1
        return float(np.asarray(prediction[0]).reshape(-1)[0])


# --- Detector ---------------------------------------------------------------------------


def _check_sensitivity(value):
    if value not in THRESHOLDS:
        raise ValueError(f"Sensitivity must be one of {', '.join(THRESHOLDS)}.")
    return value


class Detector:
    """Turns step scores into detections: threshold, audible guard, warmup, refractory.

    Times are measured in audio (80 ms steps), so a backlog processed quickly still gets
    the full 2 s warmup and refractory period.
    """

    def __init__(self, pipeline, sensitivity="normal"):
        self.pipeline = pipeline
        self.sensitivity = sensitivity
        self.audible = False  # set while JARVIS itself is speaking (J3b)
        self._quiet_through = 0  # last step of the current refractory period

    @property
    def sensitivity(self):
        return self._sensitivity

    @sensitivity.setter
    def sensitivity(self, value):
        self._sensitivity = _check_sensitivity(value)

    @property
    def threshold(self):
        base = THRESHOLDS[self._sensitivity]
        return max(base, AUDIBLE_THRESHOLD) if self.audible else base

    def reset(self):
        self.pipeline.reset()
        self._quiet_through = 0

    def feed(self, pcm):
        """Scores of the detections this chunk produced (usually an empty list)."""
        scores = self.pipeline.process(pcm)
        first = self.pipeline.steps - len(scores) + 1
        accepted = []
        for step, score in enumerate(scores, start=first):
            if step <= WARMUP_STEPS or step <= self._quiet_through:
                continue
            if score < self.threshold:  # the audible guard applies before refractory starts
                continue
            self._quiet_through = step + REFRACTORY_STEPS
            accepted.append(score)
        return accepted


# --- Listener thread ---------------------------------------------------------------------


class WakeWordListener:
    """Runs the detector on its own thread, fed from a bounded queue of PCM chunks.

    ``submit(pcm)`` never blocks: when the queue is full the oldest chunk is dropped and
    counted in ``dropped``. ``on_detect(score, monotonic_time)`` is called on the listener
    thread (J3b marshals it to the event loop). The loaded models are kept across
    stop/start; each start resets the detector, so the 2 s warmup applies again.
    """

    def __init__(self, on_detect, *, sensitivity="normal", directory=None,
                 max_chunks=DEFAULT_QUEUE_CHUNKS, pipeline_factory=None, clock=time.monotonic):
        if max_chunks < 1:
            raise ValueError("max_chunks must be at least 1.")
        self._on_detect = on_detect
        self._factory = pipeline_factory or (lambda: load_pipeline(directory))
        self._clock = clock
        self._sensitivity = _check_sensitivity(sensitivity)
        self._audible = False
        self._lock = threading.Lock()
        self._ready = threading.Condition(self._lock)
        self._queue = deque()
        self._max_chunks = max_chunks
        self._thread = None
        self._stop = None
        self._pipeline = None  # kept between runs
        self._reset_requested = False
        self.dropped = 0
        self.state = "stopped"  # "stopped", "loading", "listening" or "error"
        self.error = None

    @property
    def sensitivity(self):
        return self._sensitivity

    @sensitivity.setter
    def sensitivity(self, value):
        self._sensitivity = _check_sensitivity(value)

    @property
    def audible(self):
        return self._audible

    @audible.setter
    def audible(self, value):
        self._audible = bool(value)

    @property
    def running(self):
        thread, stop = self._thread, self._stop
        return thread is not None and thread.is_alive() and not stop.is_set()

    def submit(self, pcm):
        """Queue one chunk of 16 kHz PCM16; False when the listener is not running."""
        with self._ready:
            if self._stop is None or self._stop.is_set() or self.state == "error":
                return False
            if len(self._queue) >= self._max_chunks:
                self._queue.popleft()
                self.dropped += 1
            self._queue.append((bytes(pcm), self._audible))
            self._ready.notify()
        return True

    def reset(self):
        """Forget queued audio and restart the warmup on the listener thread."""
        with self._ready:
            self._queue.clear()
            self._reset_requested = True
            self._ready.notify()

    def start(self):
        """Start the thread; False (and nothing changes) when it is already running."""
        with self._lock:
            if self.running:
                return False
            stop = threading.Event()
            self._stop = stop
            self._queue.clear()
            self._reset_requested = False
            self._thread = threading.Thread(target=self._run, args=(stop,),
                                            name="jarvis-wake-word", daemon=True)
            self._thread.start()
        return True

    def stop(self, timeout=2.0):
        """Stop and join (up to ``timeout``); True once the thread has ended."""
        with self._ready:
            thread, stop = self._thread, self._stop
            if thread is None:
                return True
            stop.set()
            self._queue.clear()
            self._ready.notify_all()
        if thread is threading.current_thread():
            return False  # called from on_detect: the loop ends after this callback
        thread.join(timeout)
        ended = not thread.is_alive()
        with self._lock:
            if ended and self._thread is thread:
                self._thread = None
        if not ended:
            _logger.warning("Wake-word listener did not stop within %.1f s.", timeout)
        return ended

    def _set_state(self, stop, state, error=None):
        with self._lock:
            if self._stop is not stop or (self.state == state and self.error == error):
                return
            self.state, self.error = state, error
        if error:
            _logger.warning("Wake-word detector %s: %s", state, error)
        else:
            _logger.info("Wake-word detector %s.", state)

    def _run(self, stop):
        self._set_state(stop, "loading")
        with self._lock:
            pipeline, self._pipeline = self._pipeline, None
        try:
            if pipeline is None:
                pipeline = self._factory()
            detector = Detector(pipeline, self._sensitivity)
            detector.reset()
        except WakeWordError as exc:
            self._set_state(stop, "error", str(exc))
            return
        except Exception as exc:  # a broken install or model: report, never crash the core
            self._set_state(stop, "error",
                            f"The wake-word detector could not start ({type(exc).__name__}).")
            return
        failed = False
        try:
            if not stop.is_set():
                self._set_state(stop, "listening")
            while True:
                with self._ready:
                    while not self._queue and not stop.is_set() and not self._reset_requested:
                        self._ready.wait(0.5)
                    if stop.is_set():
                        break
                    reset, self._reset_requested = self._reset_requested, False
                    chunk, audible = self._queue.popleft() if self._queue else (None, False)
                    detector.sensitivity = self._sensitivity
                    detector.audible = audible or self._audible
                if reset:
                    detector.reset()
                if chunk is None:
                    continue
                for score in detector.feed(chunk):
                    _logger.info("Wake phrase heard (score %.2f).", score)
                    try:
                        self._on_detect(score, self._clock())
                    except Exception as exc:
                        _logger.warning("Wake-word callback failed (%s).", type(exc).__name__)
        except Exception as exc:
            failed = True
            self._set_state(stop, "error",
                            f"The wake-word detector stopped ({type(exc).__name__}).")
        finally:
            with self._lock:
                if self._pipeline is None:
                    self._pipeline = pipeline
        if not failed:
            self._set_state(stop, "stopped")
