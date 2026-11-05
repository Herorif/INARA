/* Gapless 24 kHz PCM16 playback with a small jitter buffer. Self-contained: shipped as a
   'self' file for the production CSP. Converts to the context rate by linear interpolation
   when the output device does not run at 24 kHz. A flush drops everything buffered. */
class VoicePlayerProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const config = options?.processorOptions || {};
    this.inputRate = config.inputRate || 24000;
    this.step = this.inputRate / sampleRate; // input samples consumed per output sample
    const primeMs = config.primeMs ?? 80;
    this.prime = Math.max(1, Math.round(primeMs * this.inputRate / 1000));
    // A short tail below the jitter target still starts after waiting primeMs.
    this.patience = Math.round(primeMs * sampleRate / 1000);
    this.waited = 0;
    this.capacity = Math.round(this.inputRate * (config.maxSeconds ?? 30));
    this.ring = new Float32Array(this.capacity);
    this.read = 0;
    this.size = 0;
    this.position = 0;
    this.playing = false;
    this.blocks = 0;
    this.energy = 0;
    this.samples = 0;
    this.port.onmessage = event => this.message(event.data);
  }
  message(data) {
    // Structured clones arrive as this realm's ArrayBuffer; the tag check also holds across realms.
    if (Object.prototype.toString.call(data) === '[object ArrayBuffer]') this.push(new Int16Array(data, 0, data.byteLength >> 1));
    else if (data?.type === 'flush') this.flush();
  }
  push(samples) {
    for (let index = 0; index < samples.length; index++) {
      if (this.size === this.capacity) {
        this.read = (this.read + 1) % this.capacity; // overflow: drop the oldest audio
        this.size--;
      }
      this.ring[(this.read + this.size) % this.capacity] = samples[index] / 32768;
      this.size++;
    }
  }
  flush() {
    const was = this.playing || this.size > 0;
    this.read = this.size = this.position = this.waited = 0;
    this.playing = false;
    this.port.postMessage({ type: 'flushed', was });
  }
  sample(offset) {
    return this.ring[(this.read + offset) % this.capacity];
  }
  process(_inputs, outputs) {
    const out = outputs[0]?.[0];
    if (!out) return true;
    if (!this.playing && this.size > 0) {
      this.waited += out.length;
      if (this.size >= this.prime || this.waited >= this.patience) {
        this.playing = true;
        this.waited = 0;
        this.port.postMessage({ type: 'playing' });
      }
    }
    for (let index = 0; index < out.length; index++) {
      if (!this.playing || this.size === 0) {
        out[index] = 0;
        continue;
      }
      const whole = Math.floor(this.position);
      const fraction = this.position - whole;
      const first = this.sample(whole);
      const second = whole + 1 < this.size ? this.sample(whole + 1) : first;
      const value = first + (second - first) * fraction;
      out[index] = value;
      this.energy += value * value;
      this.samples++;
      this.position += this.step;
      const used = Math.min(Math.floor(this.position), this.size);
      this.read = (this.read + used) % this.capacity;
      this.size -= used;
      this.position -= used;
    }
    for (let channel = 1; channel < outputs[0].length; channel++) outputs[0][channel].set(out);
    if (this.playing && this.size === 0) {
      // Underrun or end of speech: wait for a fresh jitter buffer before playing again.
      this.playing = false;
      this.position = 0;
      this.port.postMessage({ type: 'drained' });
    }
    if (++this.blocks % 8 === 0 && this.samples) {
      this.port.postMessage({ type: 'level', value: Math.min(1, Math.sqrt(this.energy / this.samples) * 4) });
      this.energy = this.samples = 0;
    }
    return true;
  }
}
registerProcessor('jarvis-voice-player', VoicePlayerProcessor);
