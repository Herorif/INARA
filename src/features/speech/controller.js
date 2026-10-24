import { createSpeechClient } from '../../transport/speechClient.ts';
import { PttCapture } from './capture.js';
import { LocalSpeech } from './playback.js';
/** Panel-owned media, bounded frame delivery, and no reconnect/retry replay. */
export class SpeechController {
  constructor({
    socket,
    onChange,
    onAnswer,
    capture = new PttCapture(),
    playback = new LocalSpeech()
  }) {
    Object.assign(this, {
      socket,
      onChange,
      onAnswer,
      capture,
      playback
    });
    this.generation = 0;
    this.queue = [];
    this.state = 'idle';
    this.closed = false;
    this.bind();
  }
  bind() {
    this.client = createSpeechClient(this.socket);
    this.client.on('disconnect', () => this.cancel('Core disconnected. Start a new turn after reconnecting.'));
    this.client.on('speech_state', value => {
      if (value?.turn_id !== this.turnId || value.project !== this.project || value.conversation_id !== this.conversationId) return;
      if (value.state === 'error') {
        this.cancel(value.message || 'Speech stopped.');
        return;
      }
      if (typeof value.transcript === 'string' && value.transcript.length <= 12000) this.update(value.state, {
        transcript: value.transcript
      });
    });
  }
  update(state, extra = {}) {
    this.state = state;
    if (!this.closed) this.onChange({
      state,
      ...extra
    });
  }
  async cancel(message = '') {
    this.generation++;
    this.recording = false;
    clearTimeout(this.timer);
    this.queue = [];
    const id = this.turnId;
    this.turnId = null;
    if (id && this.socket.connected) this.socket.emit('speech_cancel', {
      turn_id: id
    });
    this.client.dispose();
    this.playback.stop();
    this.update('idle', {
      error: message,
      transcript: '',
      cancelledTurnId: id
    });
    if (!this.closed) this.bind();
    await this.capture.stop();
    await this.delivery?.catch(() => {});
  }
  async begin({
    project,
    conversationId,
    deviceId
  }) {
    await this.cancel();
    if (this.closed) return;
    const generation = this.generation;
    this.project = project;
    this.conversationId = conversationId;
    this.turnId = crypto.randomUUID();
    this.sequence = 0;
    this.update('opening', {
      error: '',
      answer: '',
      transcript: ''
    });
    try {
      await this.client.call('speech_begin', {
        turn_id: this.turnId,
        conversation_id: conversationId
      }, 70000);
      if (generation !== this.generation) return;
      this.update('armed');
      this.timer = setTimeout(() => this.cancel('Voice preparation expired. Prepare a new turn.'), 20000);
    } catch (error) {
      if (generation === this.generation) await this.cancel(error.message);
    }
  }
  async record(deviceId) {
    if (this.state !== 'armed') return;
    const generation = this.generation;
    clearTimeout(this.timer);
    this.recording = true;
    this.update('opening');
    try {
      const ready = await this.capture.start({
        deviceId,
        onFrame: buffer => this.frame(buffer, generation),
        onFailure: message => this.cancel(message)
      });
      if (generation !== this.generation || !ready) return;
      this.update('listening');
      this.timer = setTimeout(() => this.release(), 20000);
    } catch (error) {
      if (generation === this.generation) await this.cancel(error.message);
    }
  }
  frame(buffer, generation) {
    if (!this.recording || generation !== this.generation) return;
    if (this.sequence >= 1000) {
      this.release();
      return;
    }
    if (this.queue.length >= 8) {
      this.cancel('Audio delivery fell behind. Record a shorter turn or type instead.');
      return;
    }
    const bytes = new Uint8Array(buffer);
    let raw = '';
    for (const value of bytes) raw += String.fromCharCode(value);
    const sequence = this.sequence++;
    this.queue.push({
      turn_id: this.turnId,
      codec: 'pcm_s16le',
      sample_rate: 16000,
      channels: 1,
      sequence,
      timestamp_ms: sequence * 20,
      duration_ms: 20,
      data: btoa(raw)
    });
    this.drain(generation).catch(error => {
      if (generation === this.generation) this.cancel(error.message);
    });
  }
  drain(generation) {
    if (this.delivery) return this.delivery;
    this.delivery = (async () => {
      while (this.queue.length && generation === this.generation) {
        const frame = this.queue.shift();
        const result = await this.client.call('speech_frame', frame, 3000);
        if (result.sequence !== frame.sequence) throw Error('Audio acknowledgement was out of order. Start again.');
      }
    })().finally(() => {
      this.delivery = null;
    });
    return this.delivery;
  }
  async release() {
    if (this.state === 'opening') {
      await this.cancel();
      return;
    }
    if (!this.recording) return;
    const generation = this.generation;
    this.recording = false;
    clearTimeout(this.timer);
    await this.capture.stop();
    if (generation !== this.generation) return;
    this.update('transcribing');
    try {
      await this.drain(generation);
      if (generation !== this.generation) return;
      const result = await this.client.call('speech_finish', {
        turn_id: this.turnId
      }, 45000);
      if (generation === this.generation) this.update('review', {
        transcript: result.text
      });
    } catch (error) {
      if (generation === this.generation) await this.cancel(error.message);
    }
  }
  async send(text, speak) {
    if (this.state !== 'review' || !text.trim()) return;
    const generation = this.generation;
    this.update('thinking', {
      error: ''
    });
    try {
      const result = await this.client.call('speech_send', {
        turn_id: this.turnId,
        text
      }, 180000);
      if (generation !== this.generation) return;
      this.turnId = null;
      if (result.memory_sources?.length) this.onAnswer(text, result.text, result.memory_sources);
      else this.onAnswer(text, result.text);
      this.update('answered', {
        answer: result.text,
        transcript: ''
      });
      if (speak) {
        this.update('speaking');
        await this.playback.speak(result.text);
        if (generation === this.generation) this.update('answered');
      }
    } catch (error) {
      if (generation === this.generation) await this.cancel(error.message);
    }
  }
  dispose() {
    this.closed = true;
    return this.cancel();
  }
}
