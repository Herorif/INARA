/** Gapless speaker output for live voice; no APIs are called at module load. */
export class VoicePlayer {
  constructor({
    AudioContext = globalThis.AudioContext,
    WorkletNode = globalThis.AudioWorkletNode,
    onChange = () => {},
    rate = 24000,
    primeMs = 80
  } = {}) {
    Object.assign(this, { Context: AudioContext, WorkletNode, onChange, rate, primeMs });
    this.context = null;
    this.node = null;
    this.opening = null;
    this.playing = false;
    this.buffered = false;
  }
  /** Call from a user gesture so the context may start; safe to call repeatedly. */
  open() {
    if (this.node) return Promise.resolve(true);
    if (!this.opening) this.opening = this.create().finally(() => { this.opening = null; });
    return this.opening;
  }
  async create() {
    if (!this.Context || !this.WorkletNode) throw Error('Spoken replies are unavailable here. Captions still appear.');
    let context;
    try {
      // The browser resamples a 24 kHz context to the output device.
      context = new this.Context({ sampleRate: this.rate, latencyHint: 'interactive' });
    } catch {
      // The worklet interpolates to the device rate instead.
      context = new this.Context({ latencyHint: 'interactive' });
    }
    try {
      await context.audioWorklet.addModule(new URL('./playback.worklet.js', import.meta.url));
      const node = new this.WorkletNode(context, 'inara-voice-player', {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { inputRate: this.rate, primeMs: this.primeMs }
      });
      node.port.onmessage = event => this.message(event.data);
      node.connect(context.destination);
      await context.resume();
      if (this.closed) throw Error('Playback closed.');
      this.context = context;
      this.node = node;
      return true;
    } catch (error) {
      await context.close().catch(() => {});
      throw error;
    }
  }
  message(data) {
    if (data?.type === 'playing') this.set(true);
    else if (data?.type === 'drained' || data?.type === 'flushed') this.set(false);
    else if (data?.type === 'level' && Number.isFinite(data.value)) this.onChange({ level: data.value });
  }
  set(playing) {
    if (this.playing === playing) return;
    this.playing = playing;
    this.onChange({ playing });
  }
  /** Queue one PCM16 24 kHz chunk; ownership of the buffer moves to the audio thread. */
  enqueue(buffer) {
    if (!this.node || !(buffer instanceof ArrayBuffer) || buffer.byteLength < 2) return false;
    this.node.port.postMessage(buffer, [buffer]);
    return true;
  }
  flush() {
    this.node?.port.postMessage({ type: 'flush' });
    this.set(false);
  }
  async close() {
    this.closed = true;
    await this.opening?.catch(() => {});
    const { node, context } = this;
    this.node = this.context = null;
    if (node) {
      node.port.onmessage = null;
      node.disconnect();
    }
    this.set(false);
    await context?.close().catch(() => {});
    this.closed = false;
  }
}
