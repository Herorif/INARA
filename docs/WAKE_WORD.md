# "Hey Jarvis" wake word

JARVIS can listen for the phrase "Hey Jarvis" with a small local detector:
`backend/services/wake_word.py`, a port of the openWakeWord v0.5.1 streaming pipeline
running its pre-trained ONNX models on the CPU.

This task (J3a) adds the detector, its setup and these docs. The tray and Preferences
switch, and the wiring into the microphone, arrive with J3b.

## What runs where

- Detection is local only. Microphone audio (16 kHz mono PCM16) is scored on this PC
  by three ONNX models through onnxruntime, on a dedicated listener thread, off the
  asyncio loop.
- Nothing leaves the PC until the phrase is heard. The detector has no network code;
  only after a detection does JARVIS start a voice session.
- Audio and per-frame scores are never logged or stored. The log records state changes
  (loading, listening, stopped, errors) and the score of each accepted detection.
- onnxruntime runs with the CPU execution provider only, one intra-op and one inter-op
  thread, sequential execution and error-level logging. Its telemetry events are
  switched off before any session is created.

Pipeline per 80 ms step (1280 samples; chunks of any size are gathered and the
remainder carried over):

1. mel model: the last 1280 + 480 samples, as float32 of the raw int16 values, give 8
   frames of 32 mel bins, transformed by `x / 10 + 2`;
2. embedding model: the last 76 mel frames, shaped (1, 76, 32, 1), give one 96-value
   embedding;
3. wake model: the last 16 embeddings, shaped (1, 16, 96), give a score in [0, 1].

## Model files

Folder: `JARVIS_WAKE_WORD_DIR`, else `%LOCALAPPDATA%\JARVIS\models\wake-word`.

| File | Bytes | SHA-256 |
| --- | --- | --- |
| `melspectrogram.onnx` | 1087958 | `ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f` |
| `embedding_model.onnx` | 1326578 | `70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f` |
| `hey_jarvis_v0.1.onnx` | 1271370 | `94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb` |

Source: `https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/<file>`.
GitHub publishes no digests for these assets; the hashes above are JARVIS's pins
(`MANIFEST` in `wake_word.py`).

Before loading, each file's size is checked, then the SHA-256 of the bytes read, and
the sessions are built from those same bytes (the file is not read again between the
check and the load). A missing or changed file stops the detector with a plain reason.
`status()` (for capability views) reports `installed`, `models` (`ok`, `missing`,
`changed`), `available` and `reason` without importing numpy or onnxruntime; its hash
check is cached by file size and modification time.

## Licences

- Code: the port in `backend/services/wake_word.py` is a modified version of
  openWakeWord (Copyright 2022 David Scripka), licensed under the Apache License,
  Version 2.0. See [LICENSES/Apache-2.0.txt](../LICENSES/Apache-2.0.txt).
- Models: the openWakeWord pre-trained models are licensed CC BY-NC-SA 4.0, for
  personal, non-commercial use. They are never committed to git and never shipped in
  any JARVIS package; each owner fetches them onto their own PC.

## Setup

1. Install the optional wake-word extras (onnxruntime and numpy; the core lock stays
   numpy-free, so tray voice works without them):

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-wake.txt
   ```

2. Fetch the models (HTTPS verified against the Windows certificate store; each file is
   written to a temporary file, checked by size and SHA-256 and only then renamed into
   place, and a mismatch deletes it and fails):

   ```powershell
   .\.venv\Scripts\python.exe scripts\fetch-wake-word-models.py
   ```

   To verify the files already there without downloading anything:

   ```powershell
   .\.venv\Scripts\python.exe scripts\fetch-wake-word-models.py --check
   ```

## Detection rules

| Sensitivity | Threshold |
| --- | --- |
| low | 0.70 |
| normal | 0.50 |
| high | 0.35 |

- Warmup: no detection is reported until 2 s of audio (25 steps) has been processed
  after a start or `reset()`. Upstream instead seeds its buffers (mel frames of ones,
  embeddings of random noise) and zeroes its first 5 predictions; after the warmup every
  wake-model input comes from real audio, so scores equal upstream's for the same audio.
- Refractory period: after a detection, nothing more for 2 s of audio.
- While JARVIS is speaking (`audible`, set by J3b) the threshold is at least 0.70. This
  is checked before a detection is accepted, so a score rejected by it starts no
  refractory period.
- `submit()` never blocks: the listener queue is bounded and drops the oldest chunk
  when full, counting drops in `dropped`. `on_detect(score, monotonic_time)` is called
  on the listener thread.

## Measured

On the development PC, with the real models on Windows text-to-speech clips (the opt-in
`live_wake` test, `JARVIS_LIVE_WAKE_TESTS=1`):

- "Hey Jarvis" in Microsoft David and Microsoft Zira at rates 0 and 3: all detected at
  normal sensitivity (maximum scores 0.998 to 0.999);
- "Hey Travis", "Hello there", "Hey Siri" and "What's the weather like" in both voices,
  silence and white noise at -30 dBFS: none detected. The highest maximum was "Hey
  Travis" in Zira, 0.42: below the normal threshold but above the high one, so high
  sensitivity can wake on close rhymes; every other negative stayed under 0.07;
- CPU: about 18 ms of thread CPU time per second of audio, 1.8 % of one core, against a
  target of under 3 %.
