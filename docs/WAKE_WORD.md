# "Hey Jarvis" wake word

JARVIS can listen for the phrase "Hey Jarvis" with a small local detector:
`backend/services/wake_word.py`, a port of the openWakeWord v0.5.1 streaming pipeline
running its pre-trained ONNX models on the CPU.

Saying "Hey Jarvis" starts tray voice hands-free, with the workspace open or closed.

## Turning it on and off

- It is on by default (`voice.wake_word`, with `voice.wake_sensitivity` low, normal or
  high, default normal). A missing or unreadable saved value counts as the default.
- In the tray menu, **Listen for "Hey Jarvis"** is checked while it is on; choosing it
  switches it and saves the setting, exactly as Preferences does, so an open Preferences
  page shows the change.
- In Preferences, the voice section has the same switch, the sensitivity and a status
  line.
- Turning it off releases the microphone and unloads the detector, so the resident is
  back to tray voice only (numpy and onnxruntime, once imported, stay loaded until
  JARVIS restarts).

Listening runs only in the JARVIS tray app (the native resident), in the resident, chat
and studio states. The microphone is held only while all of these hold: the switch is
on, the extras and models are installed, the desktop owner is registered, a Gemini API
key is set, microphone permission is not turned off, gaming mode is off, and a
microphone is connected. JARVIS checks again when settings, the resource state or the
owner change, after each tray voice session, and every 30 s while it is not listening
(so a key or the models added later are picked up).

## What each state means

The tray tooltip and the Preferences status line show one of:

| State | Tooltip | Meaning |
| --- | --- | --- |
| listening | `Listening for "Hey Jarvis"` | The microphone is open and the detector runs (including the moment the models load). |
| paused | `"Hey Jarvis" paused` | Gaming mode is on; the microphone is closed. It listens again when gaming mode ends. |
| unavailable | `"Hey Jarvis" unavailable` | Something is missing; Preferences says what: the extras, the models, the Gemini key, the owner, microphone permission, no microphone, a disconnected microphone, or a detector error. |
| off | (nothing) | The switch is off. |

While a tray voice session runs, the tooltip shows that session instead.

There is only ever one capture stream. While listening, the microphone opens at 16 kHz
mono (Windows converts it), or at the device's own rate and resampled on a capture
thread when the device refuses. It stays open across tray voice sessions: Talk to JARVIS
and "Hey Jarvis" both reuse it, and ending a session leaves it open. A disconnected
microphone is tried again after 10 s, 30 s, then every 60 s, each time with the saved
device or the system default. Opening Preferences' device list briefly releases it so
Windows can report new devices, unless a session is running.

## When the phrase is heard

- No voice session: a short rising cue (660 then 880 Hz), then tray voice starts.
- A workspace voice session: ignored.
- A tray session while JARVIS is talking: **barge-in**. Gemini cannot hear you while
  JARVIS speaks (the microphone is paused to Gemini then, so JARVIS does not hear
  itself), so the phrase interrupts it here: playback stops at once, the microphone
  reaches Gemini immediately, and the rest of the interrupted answer is dropped until
  Gemini ends that turn (or 5 s). No cue plays; just say what you want.
- A tray session while JARVIS is quiet: ignored; Gemini already hears you.

The cues play on the tray voice speaker and never pause the microphone, so you can talk
straight through them.

**Pre-roll.** JARVIS keeps the last 1.5 s of microphone audio in memory, overwriting it
continuously; it is never stored or logged. Only after a detection starts a session is
it sent to Gemini, before the live audio: it holds the phrase itself plus a moment
before it, so a request said in one breath ("Hey Jarvis, what's on today?") is heard
whole. A session started from the tray menu sends none, and neither does a barge-in
(it would contain JARVIS's own voice).

**Face lock.** Listening continues while JARVIS is locked, but the phrase cannot start
voice: a falling cue (523 then 392 Hz) plays, the tray shows why, and a notification
says "Unlock JARVIS in the workspace to talk." (at most once every 10 minutes).

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
- While JARVIS is speaking (`audible`, kept in step with tray voice playback) the
  threshold is at least 0.70. This is checked before a detection is accepted, so a
  score rejected by it starts no refractory period.
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

Idle listening, measured as the whole process's CPU time against wall-clock time over
60 s of synthetic 20 ms blocks fed through the microphone's real callback path into the
listener (a fake audio device, so no real microphone; the simulated device thread is
included):

- real models, 16 kHz stream from Windows (the normal case): 2.7 % of one core
  (27 ms of CPU per second);
- real models, a microphone that refuses 16 kHz (device rate, resampled): 4.6 % of
  one core (46 ms per second);
- fake models (the capture path alone, plus a small stand-in pipeline): 1.2 %.

No block was dropped in any run. Real microphones may differ.
