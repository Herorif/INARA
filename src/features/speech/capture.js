/** Exclusive browser microphone ownership; no APIs are called at module load. */
let owner = null;
export class PttCapture {
  constructor({
    media = globalThis.navigator?.mediaDevices,
    AudioContext = globalThis.AudioContext,
    WorkletNode = globalThis.AudioWorkletNode
  } = {}) {
    this.media = media;
    this.Context = AudioContext;
    this.WorkletNode = WorkletNode;
    this.generation = 0;
    this.pending = false;
  }
  async start({
    deviceId,
    onFrame,
    onFailure
  }) {
    if (owner) throw Error('Another microphone request is active. Finish or dismiss it before trying again.');
    if (!this.media?.getUserMedia || !this.Context || !this.WorkletNode) throw Error('Push-to-talk is unavailable here. Type a message instead.');
    owner = this;
    this.pending = true;
    const generation = ++this.generation;
    try {
      const stream = await this.media.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          ...(deviceId ? {
            deviceId: {
              exact: deviceId
            }
          } : {})
        },
        video: false
      });
      this.pending = false;
      if (generation !== this.generation) {
        stream.getTracks().forEach(track => track.stop());
        return false;
      }
      this.stream = stream;
      const track = stream.getAudioTracks()[0];
      if (!track) throw Error('No microphone track is available.');
      if (deviceId && track.getSettings?.().deviceId !== deviceId) throw Error('The selected microphone changed. Choose it again.');
      const fail = () => {
        if (generation === this.generation) {
          onFailure('The microphone was lost or suspended. Press to talk again.');
          this.stop();
        }
      };
      track.addEventListener('ended', fail);
      track.addEventListener('mute', fail);
      this.deviceChanged = async () => {
        try {
          const devices = await this.media.enumerateDevices();
          if (generation === this.generation && track.getSettings?.().deviceId && !devices.some(device => device.kind === 'audioinput' && device.deviceId === track.getSettings().deviceId)) fail();
        } catch {
          fail();
        }
      };
      this.media.addEventListener?.('devicechange', this.deviceChanged);
      this.context = new this.Context({
        sampleRate: 16000
      });
      if (this.context.sampleRate < 16000) throw Error('This audio sample rate is unsupported. Type a message instead.');
      await this.context.audioWorklet.addModule(new URL('./pcm.worklet.js', import.meta.url));
      if (generation !== this.generation) return false;
      this.node = new this.WorkletNode(this.context, 'inara-ptt');
      this.node.port.onmessage = event => {
        if (generation === this.generation && event.data?.byteLength === 640) onFrame(event.data);
      };
      this.source = this.context.createMediaStreamSource(stream);
      this.silent = this.context.createGain();
      this.silent.gain.value = 0;
      this.source.connect(this.node);
      this.node.connect(this.silent);
      this.silent.connect(this.context.destination);
      this.context.onstatechange = () => {
        if (this.context?.state === 'suspended') fail();
      };
      await this.context.resume();
      return generation === this.generation;
    } catch (error) {
      await this.stop();
      throw error;
    } finally {
      this.pending = false;
      if (generation !== this.generation && owner === this) owner = null;
    }
  }
  async stop() {
    this.generation++;
    this.media?.removeEventListener?.('devicechange', this.deviceChanged);
    if (this.node) {
      this.node.port.onmessage = null;
      this.node.port.close?.();
      this.node.disconnect();
      this.node = null;
    }
    this.source?.disconnect();
    this.source = null;
    this.silent?.disconnect();
    this.silent = null;
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = null;
    const context = this.context;
    this.context = null;
    if (context) {
      context.onstatechange = null;
      await context.close().catch(() => {});
    }
    if (!this.pending && owner === this) owner = null;
  }
}
