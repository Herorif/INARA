// Pure mappings for the VOICE group in Preferences: the prebuilt voice list (grouped and
// described), the default voice mode, preview failures, and the one-at-a-time preview player.

// Descriptors from the "Voice options" table of
// https://ai.google.dev/gemini-api/docs/speech-generation (page last updated 2026-10-12 UTC,
// checked 27 Oct 2026). backend/services/live_config.py PREBUILT_VOICES holds the same 30
// names without descriptors; tests/test_voice_preview.py checks the two lists match.
export const VOICE_DESCRIPTORS = {
  Zephyr: 'Bright', Puck: 'Upbeat', Charon: 'Informative', Kore: 'Firm', Fenrir: 'Excitable',
  Leda: 'Youthful', Orus: 'Firm', Aoede: 'Breezy', Callirrhoe: 'Easy-going', Autonoe: 'Bright',
  Enceladus: 'Breathy', Iapetus: 'Clear', Umbriel: 'Easy-going', Algieba: 'Smooth', Despina: 'Smooth',
  Erinome: 'Clear', Algenib: 'Gravelly', Rasalgethi: 'Informative', Laomedeia: 'Upbeat', Achernar: 'Soft',
  Alnilam: 'Firm', Schedar: 'Even', Gacrux: 'Mature', Pulcherrima: 'Forward', Achird: 'Friendly',
  Zubenelgenubi: 'Casual', Vindemiatrix: 'Gentle', Sadachbia: 'Lively', Sadaltager: 'Knowledgeable', Sulafat: 'Warm',
};

export const DEFAULT_VOICE = 'Kore';
// Female-sounding voices first, in this order.
export const SUGGESTED_VOICES = ['Kore', 'Despina', 'Erinome', 'Sulafat', 'Aoede', 'Leda', 'Zephyr', 'Autonoe', 'Callirrhoe'];

export const VOICE_MODES = [
  { id: 'push_to_talk', label: 'Push to talk', help: 'Hold the hotkey or button while you speak.' },
  { id: 'conversation', label: 'Conversation', help: 'Talk hands-free; JARVIS listens until you stop the conversation.' },
];
export const DEFAULT_MODE = 'push_to_talk';
export const PREVIEW_NO_KEY = 'Add a Gemini key to preview voices.';

const entry = name => ({ name, descriptor: VOICE_DESCRIPTORS[name], isDefault: name === DEFAULT_VOICE });

/** { suggested, other }: the suggested voices in their order, then the rest alphabetically. */
export function voiceGroups() {
  const suggested = SUGGESTED_VOICES.map(entry);
  const other = Object.keys(VOICE_DESCRIPTORS).filter(name => !SUGGESTED_VOICES.includes(name))
    .sort((a, b) => a.localeCompare(b)).map(entry);
  return { suggested, other };
}

/** Saved `settings.voice` -> { name, mode }, with the core's fallbacks for unknown values. */
export function voiceChoice(voice) {
  const value = voice && typeof voice === 'object' ? voice : {};
  return {
    name: Object.hasOwn(VOICE_DESCRIPTORS, value.name) ? value.name : DEFAULT_VOICE,
    mode: VOICE_MODES.some(item => item.id === value.mode) ? value.mode : DEFAULT_MODE,
  };
}

export function modeHelp(mode) {
  return (VOICE_MODES.find(item => item.id === mode) || VOICE_MODES[0]).help;
}

/** Plain sentence for a failed preview; the core already sends plain messages for its codes. */
export function previewFailureMessage(error) {
  const code = error && typeof error === 'object' ? error.code : undefined;
  if (code === 'provider_not_configured') return PREVIEW_NO_KEY;
  if (code === 'offline' || code === 'disconnected') return 'JARVIS core is offline. Reconnect and try again.';
  if (code === 'timeout') return 'The preview took too long. Try again.';
  if (code === 'playback') return 'This device could not play the preview.';
  if (code === 'invalid_response' || code === 'send_failed' || code === 'scope_closed') return 'The voice preview could not play. Try again.';
  const message = error && typeof error === 'object' && typeof error.message === 'string' ? error.message : '';
  return message || 'The voice preview could not play. Try again.';
}

/** Base64 PCM16 mono little-endian -> Float32 samples in [-1, 1). */
export function decodePcm16(base64) {
  const binary = atob(base64);
  const count = binary.length >> 1;
  const samples = new Float32Array(count);
  for (let index = 0; index < count; index++) {
    const low = binary.charCodeAt(index * 2), high = binary.charCodeAt(index * 2 + 1);
    let value = (high << 8) | low;
    if (value >= 0x8000) value -= 0x10000;
    samples[index] = value / 32768;
  }
  return samples;
}

/**
 * One preview at a time. `fetch(name)` resolves { sample_rate, pcm_base64 }; `onChange`
 * receives { playing: name | null, loading: name | null, error: { name, message } | null }.
 * Starting a preview stops the current one; `close()` stops and releases the AudioContext.
 */
export class PreviewPlayer {
  constructor({ fetch, onChange = () => {}, AudioContext = globalThis.AudioContext } = {}) {
    Object.assign(this, { fetch, onChange, Context: AudioContext });
    this.context = null;
    this.source = null;
    this.token = 0;
    this.state = { playing: null, loading: null, error: null };
  }
  set(patch) {
    this.state = { ...this.state, ...patch };
    this.onChange(this.state);
  }
  /** Toggle: the playing (or loading) voice stops; any other voice replaces it. */
  async toggle(name) {
    if (this.state.playing === name || this.state.loading === name) { this.stop(); return; }
    await this.play(name);
  }
  async play(name) {
    this.halt();
    const token = ++this.token;
    this.set({ playing: null, loading: name, error: null });
    try {
      // Created inside the click so the context may start.
      if (!this.context) {
        if (!this.Context) throw Object.assign(new Error('playback'), { code: 'playback' });
        this.context = new this.Context();
      }
      const sample = await this.fetch(name);
      if (token !== this.token) return;
      const samples = decodePcm16(sample.pcm_base64);
      const context = this.context;
      if (!context || !samples.length) throw Object.assign(new Error('playback'), { code: 'playback' });
      await context.resume?.();
      if (token !== this.token) return;
      const buffer = context.createBuffer(1, samples.length, sample.sample_rate);
      buffer.copyToChannel(samples, 0);
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      source.onended = () => {
        if (this.source !== source) return;
        this.source = null;
        this.set({ playing: null });
      };
      this.source = source;
      source.start();
      this.set({ playing: name, loading: null });
    } catch (error) {
      if (token !== this.token) return;
      this.set({ playing: null, loading: null, error: { name, message: previewFailureMessage(error) } });
    }
  }
  halt() {
    const source = this.source;
    this.source = null;
    if (source) {
      source.onended = null;
      try { source.stop(); } catch { /* already stopped */ }
      source.disconnect?.();
    }
  }
  stop() {
    this.token++;
    this.halt();
    if (this.state.playing || this.state.loading) this.set({ playing: null, loading: null });
  }
  close() {
    this.stop();
    const context = this.context;
    this.context = null;
    context?.close?.().catch?.(() => {});
  }
}
