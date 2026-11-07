import { captureDecision, defaultInputKey } from '../voice/microphoneModel.js';

const LOST = 'The microphone was lost or suspended. Press to talk again.';
const RECOVERIES = 2; // reopens in a row without a frame in between before the capture ends

/**
 * Exclusive browser microphone ownership; no APIs are called at module load. `deviceId` is a
 * browser deviceId, '' for the default device, or an async function resolving to one when the
 * capture opens. On the default device (Automatic) an open capture moves to a new Windows
 * default by itself; a chosen device that disappears ends the capture.
 */
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
    this.request = null;
    this.restarting = false;
    this.recoveries = 0;
  }
  async start({
    deviceId,
    onFrame,
    onFailure
  }) {
    if (owner) throw Error('Another microphone request is active. Finish or dismiss it before trying again.');
    if (!this.media?.getUserMedia || !this.Context || !this.WorkletNode) throw Error('Push-to-talk is unavailable here. Type a message instead.');
    owner = this;
    this.request = { deviceId, onFrame, onFailure };
    this.recoveries = 0;
    try {
      return await this.open();
    } catch (error) {
      await this.stop();
      throw error;
    }
  }
  async open() {
    const { deviceId: wanted, onFrame, onFailure } = this.request;
    this.pending = true;
    const generation = ++this.generation;
    try {
      const deviceId = (typeof wanted === 'function' ? await wanted() : wanted) || '';
      if (generation !== this.generation) return false;
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
          onFailure(LOST);
          this.stop();
        }
      };
      // The default device (Automatic): a lost track reopens on whatever Windows uses now.
      const recover = () => {
        if (generation === this.generation) this.restart();
      };
      track.addEventListener('ended', deviceId ? fail : recover);
      track.addEventListener('mute', deviceId ? fail : recover);
      const devices = async () => (typeof this.media.enumerateDevices === 'function' ? this.media.enumerateDevices() : []);
      const defaultKey = deviceId ? '' : defaultInputKey(await devices().catch(() => []));
      if (generation !== this.generation) return false;
      this.deviceChanged = async () => {
        try {
          const listed = await devices();
          if (generation !== this.generation) return;
          const decision = captureDecision({ deviceId, trackDeviceId: track.getSettings?.().deviceId, defaultKey, devices: listed });
          if (decision === 'lost') fail();
          else if (decision === 'restart') recover();
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
      this.node = new this.WorkletNode(this.context, 'jarvis-ptt');
      this.node.port.onmessage = event => {
        if (generation !== this.generation || event.data?.byteLength !== 640) return;
        this.recoveries = 0;
        onFrame(event.data);
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
    } finally {
      this.pending = false;
      // Stopped while opening: ownership ends here (a restart keeps it).
      if (generation !== this.generation && owner === this && !this.request) owner = null;
    }
  }
  /** Reopen on the current default device, keeping ownership and the frame callback. */
  async restart() {
    if (this.restarting || !this.request) return;
    if (++this.recoveries > RECOVERIES) {
      const request = this.request;
      await this.stop();
      request.onFailure(LOST);
      return;
    }
    this.restarting = true;
    try {
      this.generation++;
      await this.release();
      if (!this.request) return;
      try {
        await this.open();
      } catch {
        const request = this.request;
        if (!request) return;
        await this.stop();
        request.onFailure(LOST);
      }
    } finally {
      this.restarting = false;
    }
  }
  async release() {
    this.media?.removeEventListener?.('devicechange', this.deviceChanged);
    this.deviceChanged = null;
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
  }
  async stop() {
    this.generation++;
    this.request = null;
    await this.release();
    if (!this.pending && owner === this) owner = null;
  }
}
