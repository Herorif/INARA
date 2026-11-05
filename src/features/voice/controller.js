import { createVoiceClient, isVoiceCaption, isVoiceInterrupted, isVoiceState, voiceAudioOut } from '../../transport/voiceClient.ts';
import { PttCapture } from '../speech/capture.js';
import { VoicePlayer } from './player.js';

const PACKET_BYTES = 1280; // 40 ms of 16 kHz PCM16 per voice_audio
const FINISHED = new Set(['ended', 'error']);

/**
 * One live voice session at a time. The microphone is open only while push-to-talk is held
 * or hands-free conversation is on; nothing is replayed after a disconnect.
 */
export class VoiceController {
  constructor({
    socket,
    onChange = () => {},
    onCaption = () => {},
    onEnd = () => {},
    capture = new PttCapture(),
    player = null
  }) {
    Object.assign(this, { socket, onChange, onCaption, onEnd, capture });
    this.player = player || new VoicePlayer({ onChange: patch => this.playback(patch) });
    this.status = { state: 'off', mode: null, micOpen: false, playing: false, level: 0, error: '' };
    this.sessionId = null;
    this.mode = null;
    this.holding = false;
    this.generation = 0;
    this.closed = false;
    this.bind();
  }
  bind() {
    this.client = createVoiceClient(this.socket);
    this.client.on('disconnect', () => this.reset('Core disconnected. Voice is off.'));
    this.client.on('voice_state', value => {
      if (!isVoiceState(value) || value.session_id !== this.sessionId) return;
      if (FINISHED.has(value.state)) {
        const quiet = value.state === 'ended' && ['stopped', 'conversation_ended', 'silence_timeout'].includes(value.code);
        this.reset(quiet ? '' : value.message || 'Voice stopped.', value.state === 'error');
        return;
      }
      this.update({ state: value.state });
    });
    this.client.on('voice_audio_out', value => {
      const chunk = voiceAudioOut(value);
      if (chunk && chunk.session_id === this.sessionId && chunk.seq > (this.outSeq || 0)) {
        this.outSeq = chunk.seq;
        this.player.enqueue(chunk.pcm);
      }
    });
    this.client.on('voice_interrupted', value => {
      if (isVoiceInterrupted(value) && value.session_id === this.sessionId) this.player.flush();
    });
    this.client.on('voice_caption', value => {
      if (!isVoiceCaption(value) || value.session_id !== this.sessionId) return;
      const role = value.role === 'user' ? 'user' : 'jarvis';
      const key = `${value.session_id}:${role}:${this.captions[role]}`;
      if (value.final) this.captions[role]++;
      this.onCaption({ key, role, text: value.text, final: value.final });
    });
  }
  update(patch) {
    this.status = { ...this.status, ...patch };
    if (!this.closed) this.onChange(this.view());
  }
  /** What the owner sees: local playback counts as speaking. */
  view() {
    const { state, playing } = this.status;
    return { ...this.status, state: playing && !['off', 'connecting'].includes(state) ? 'speaking' : state };
  }
  playback(patch) {
    this.update(patch);
  }
  active() {
    return !!this.sessionId;
  }
  async ensure(mode, conversationId) {
    if (this.sessionId && this.mode === mode) return true;
    if (this.sessionId || this.starting) await this.stop();
    const generation = ++this.generation;
    this.update({ state: 'connecting', mode, error: '' });
    this.starting = this.client.start({ mode, conversation_id: conversationId });
    try {
      const result = await this.starting;
      if (generation !== this.generation) {
        this.client.stop({ session_id: result.session_id }).catch(() => {});
        return false;
      }
      this.sessionId = result.session_id;
      this.mode = mode;
      this.seq = 0;
      this.outSeq = 0;
      this.captions = { user: 0, jarvis: 0 };
      this.update({ state: mode === 'conversation' ? 'listening' : 'idle', mode });
      return true;
    } catch (error) {
      if (generation === this.generation) this.update({ state: 'off', mode: null, error: error.message });
      return false;
    } finally {
      this.starting = null;
    }
  }
  /** Push-to-talk press: interrupts JARVIS, starts or reuses a session, opens the microphone. */
  async holdStart({ conversationId, deviceId }) {
    if (this.holding || this.mode === 'conversation') return;
    this.holding = true;
    this.player.flush();
    try {
      await this.player.open();
    } catch (error) {
      this.update({ error: error.message });
    }
    if (!this.holding) return;
    const ready = await this.ensure('push_to_talk', conversationId);
    if (!ready || !this.holding) {
      this.holding = false;
      return;
    }
    this.client.activity({ session_id: this.sessionId, state: 'start' });
    this.update({ state: 'listening' });
    await this.openMic(deviceId);
    if (!this.holding) await this.closeMic();
  }
  /** Push-to-talk release: closes the microphone and asks for the answer. */
  async holdEnd() {
    if (!this.holding) return;
    this.holding = false;
    await this.closeMic();
    if (this.sessionId && this.mode === 'push_to_talk') {
      this.client.activity({ session_id: this.sessionId, state: 'end' });
      this.update({ state: 'thinking' });
    }
  }
  /** Hands-free on/off. */
  async toggleConversation({ conversationId, deviceId }) {
    if (this.mode === 'conversation' && this.sessionId) return this.stop();
    try {
      await this.player.open();
    } catch (error) {
      this.update({ error: error.message });
    }
    if (!(await this.ensure('conversation', conversationId))) return;
    await this.openMic(deviceId);
  }
  async openMic(deviceId) {
    const generation = this.generation;
    this.packet = new Uint8Array(PACKET_BYTES);
    this.filled = 0;
    try {
      const ready = await this.capture.start({
        deviceId,
        onFrame: buffer => this.frame(buffer, generation),
        onFailure: message => this.stop(message)
      });
      if (ready && generation === this.generation) this.update({ micOpen: true });
      else await this.capture.stop();
    } catch (error) {
      if (generation === this.generation) await this.stop(error.message);
    }
  }
  frame(buffer, generation) {
    if (generation !== this.generation || !this.sessionId) return;
    const bytes = new Uint8Array(buffer);
    this.packet.set(bytes, this.filled);
    this.filled += bytes.byteLength;
    if (this.filled >= PACKET_BYTES) this.send();
  }
  send() {
    if (!this.filled || !this.sessionId) return;
    const pcm = this.packet.slice(0, this.filled).buffer;
    this.filled = 0;
    this.client.audio({ session_id: this.sessionId, seq: this.seq++, pcm });
  }
  async closeMic() {
    if (this.filled >= 640) this.send();
    this.filled = 0;
    await this.capture.stop();
    this.update({ micOpen: false });
  }
  /** Local stop: microphone off, playback flushed, session ended at the core. */
  async stop(message = '') {
    const id = this.sessionId;
    this.reset(message);
    if (id && this.socket.connected) await this.client.stop({ session_id: id }).catch(() => {});
  }
  reset(message = '', flush = true) {
    const id = this.sessionId;
    this.generation++;
    this.sessionId = null;
    this.mode = null;
    this.holding = false;
    this.filled = 0;
    if (flush) this.player.flush();
    this.capture.stop().catch(() => {});
    this.update({ state: 'off', mode: null, micOpen: false, error: message });
    if (id) this.onEnd(id);
  }
  async dispose() {
    await this.stop();
    this.closed = true;
    this.client.dispose();
    await this.player.close();
  }
}
