# Interface sounds

JARVIS plays short synthesised tones for a few moments in the workspace (9NovWork specs S13a,
"Sound"). There are no audio files: every cue is generated with WebAudio in the renderer.
Sounds never carry information alone — each cue accompanies something already on screen.

Code:

- `src/services/sound/uiSoundsModel.js` — pure logic: cue designs, mute rules, the
  scheduler (80 ms rule, thinking rate limit, settling), cue selection per event, volume
  mapping. Tested in `tests/test_ui_sounds.mjs` without a real AudioContext.
- `src/services/sound/uiSounds.js` — the thin WebAudio engine and `playCue(name)`.
- `src/services/events/sound.js` — store and socket events into cues.
- `src/services/sound/useUiSoundContext.js` — gaming mode and calls, from `CommandDeck`.
- `src/features/settings/SoundSettings.jsx` — Preferences > Sound.
- Core: `backend/services/settings.py` (`SoundSettings`, `SOUND_DEFAULTS`,
  `sound_settings`), tests in `tests/test_sound_settings.py`.

## Timbre

One family for every cue. Each note is a sine at the note's pitch plus a triangle an octave
up (30 % of the sine's level unless a cue says otherwise), with a short linear attack and an
exponential decay to silence. Glides ramp both voices exponentially. 18 % of every cue goes
to a convolver with a generated 0.3 s decaying-noise impulse response. Master gain at 100 %
volume is 0.6; the worst-case peak of any cue (all overlapping notes at full level plus the
reverb send) stays below 0.5, well clear of clipping. Every cue's notes end within 350 ms.

## Cues

| Cue | When | Design |
| --- | --- | --- |
| `wake` | A voice session starts: "Hey Jarvis", the tray's Talk to JARVIS, or the in-app voice connecting | A5 880 Hz (0–120 ms) then E6 1318.5 Hz (90–290 ms), 6 ms attacks |
| `listen` | Listening starts inside a running session (push-to-talk pressed, or a new turn) | C6 1046.5 Hz gliding to 1174.7 Hz, 90 ms, quiet |
| `thinking` | While JARVIS works on a reply; off unless `sound.thinking` is on | A3 220 Hz, 90 ms swell, 320 ms, very quiet, at most every 4 s |
| `confirm` | An approval is approved (the approval popup) | G5 784 Hz (0–110 ms) then C6 1046.5 Hz (80–260 ms) |
| `deny` | An approval is denied or dismissed | E5 659.3 Hz (0–110 ms) then B4 493.9 Hz (80–280 ms) |
| `panelOpen` | A Stage panel materialises (the Live design panel) | 600 → 1200 Hz sweep, 40 ms attack, 220 ms, airy (60 % triangle) |
| `panelClose` | That panel leaves | 1000 → 520 Hz sweep, 25 ms attack, 180 ms |
| `notify` | A new VIP call card or a new morning briefing card | E6 1318.5 Hz, 3 ms attack, 340 ms bell-like decay |

A session that is already speaking when its first snapshot arrives is a restore, not a
start, and stays silent. Tray sessions started by the morning briefing do not play `wake`;
the briefing card plays `notify`. Each notification sounds once per card (VIP by record id,
briefing by date), however often the core re-sends it.

## Rules

- **Silent** when `sound.enabled` is false, in gaming mode, while a phone call is in
  progress (`calls_status.active_call`), and at 0 % volume.
- **System mute:** the renderer cannot tell whether the Windows output is muted (neither
  Chromium nor Electron exposes it, and no native module is added for it). The model takes a
  `systemMuted` input that silences cues when it is `true`; it stays unknown (`null`) today,
  so a muted Windows output simply plays nothing audible.
- **One cue at a time:** never more than one cue inside 80 ms. A newer cue cuts the older
  one (15 ms fade). `thinking` never cuts another cue; it is dropped instead.
- **Thinking** repeats no more often than every 4 s.
- **No cue on load or restore:** the engine settles for 1.5 s at start-up, on every socket
  (re)connect and on unlock, so state the core re-sends then is silent. Cards already in the
  store at start-up count as already announced.
- **Autoplay:** no AudioContext exists until the first pointer or key press in the window.
  One context is then created on the first cue, resumed whenever it is suspended, and closed
  after the page has been hidden and idle for 60 s (it is created again on the next cue).
- **Volume** scales the master gain on a squared curve (`0.6 × volume²`), so the slider
  feels even.

## Settings

`settings.sound`, merged over defaults and patched with `update_settings` like the other
blocks:

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | Interface sounds on or off |
| `volume` | number 0–1 | `0.5` | Stored rounded to two decimals |
| `thinking` | bool | `false` | The optional thinking pulse |

`null`, an empty patch, unknown keys, a non-boolean switch and a volume outside 0–1 (or a
string, boolean, NaN or infinity) are rejected. A malformed saved value reads as its default.

## Preferences

Preferences > Sound, directly under the voice settings: the "Interface sounds" switch, a
volume slider (0–100 %, saved when it is let go), "Play a sample" (plays `confirm` at the
slider's volume; it follows every mute rule but not the settle window), and the "Thinking
sound" switch ("A very quiet pulse while JARVIS works."). The slider and the sample are
disabled while interface sounds are off.
