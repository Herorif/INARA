/* Fixed mono PCM16 framing. No buffers or messages survive a capture session. */
class PttProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0;
    this.sum = 0;
    this.count = 0;
    this.offset = 0;
    this.buffer = new ArrayBuffer(640);
    this.view = new DataView(this.buffer);
  }
  process(inputs) {
    const samples = inputs[0]?.[0];
    if (!samples) return true;
    for (const sample of samples) {
      this.sum += Number.isFinite(sample) ? sample : 0;
      this.count++;
      this.phase += 16000;
      if (this.phase >= sampleRate) {
        this.phase -= sampleRate;
        const value = Math.max(-1, Math.min(1, this.sum / this.count));
        this.sum = 0;
        this.count = 0;
        this.view.setInt16(this.offset, value < 0 ? Math.round(value * 32768) : Math.round(value * 32767), true);
        this.offset += 2;
        if (this.offset === 640) {
          this.port.postMessage(this.buffer, [this.buffer]);
          this.buffer = new ArrayBuffer(640);
          this.view = new DataView(this.buffer);
          this.offset = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('inara-ptt', PttProcessor);
