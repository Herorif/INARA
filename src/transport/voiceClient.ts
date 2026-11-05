import { createRpcScope, RpcError, type RpcSocket } from './rpc.ts';
import type { VoiceActivity, VoiceReference, VoiceStart } from './generated/voice.ts';

/** Live voice socket contract (owner renderer only). Audio is binary PCM16 mono. */
export type VoiceMode = VoiceStart['mode'];
export type VoiceState = 'connecting' | 'listening' | 'thinking' | 'working' | 'speaking' | 'idle' | 'ended' | 'error';
/** 20-100 ms of 16 kHz PCM16 mono little-endian microphone audio. */
export interface VoiceAudio { session_id: string; seq: number; pcm: ArrayBuffer }
export interface VoiceStartResult { ok: true; session_id: string; input_rate: 16000; output_rate: 24000 }
export interface VoiceStateEvent { session_id: string; state: VoiceState; code?: string; message?: string }
/** 24 kHz PCM16 mono little-endian speech from JARVIS. */
export interface VoiceAudioOut { session_id: string; seq: number; pcm: ArrayBuffer }
export interface VoiceInterrupted { session_id: string }
/** `role` 'inara' comes from a core started before the JARVIS rename (5 Nov 2026); read it as 'jarvis'. Remove one release later. */
export interface VoiceCaption { session_id: string; role: 'user' | 'jarvis' | 'inara'; text: string; final: boolean }

export interface VoiceSocket extends RpcSocket {
  emit(event: string, data: unknown, ack?: (response: unknown) => void): unknown;
}

const STATES = new Set<string>(['connecting', 'listening', 'thinking', 'working', 'speaking', 'idle', 'ended', 'error']);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object';
const sessionOf = (value: Record<string, unknown>) => typeof value.session_id === 'string' && UUID.test(value.session_id);

export function isVoiceState(value: unknown): value is VoiceStateEvent {
  return record(value) && sessionOf(value) && typeof value.state === 'string' && STATES.has(value.state)
    && (value.code === undefined || (typeof value.code === 'string' && value.code.length <= 64))
    && (value.message === undefined || (typeof value.message === 'string' && value.message.length <= 500));
}

/** Copies the PCM into its own even-length ArrayBuffer, or null when the event is invalid. */
export function voiceAudioOut(value: unknown): VoiceAudioOut | null {
  if (!record(value) || !sessionOf(value) || typeof value.seq !== 'number' || !Number.isInteger(value.seq) || value.seq < 1) return null;
  const pcm = value.pcm;
  const bytes = pcm instanceof ArrayBuffer ? new Uint8Array(pcm) : ArrayBuffer.isView(pcm) ? new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength) : null;
  // At most 10 s of 24 kHz PCM16 in one chunk.
  if (!bytes || bytes.byteLength < 2 || bytes.byteLength > 480000) return null;
  const length = bytes.byteLength - (bytes.byteLength % 2);
  return { session_id: value.session_id as string, seq: value.seq, pcm: bytes.slice(0, length).buffer as ArrayBuffer };
}

export function isVoiceInterrupted(value: unknown): value is VoiceInterrupted {
  return record(value) && sessionOf(value);
}

export function isVoiceCaption(value: unknown): value is VoiceCaption {
  return record(value) && sessionOf(value) && (value.role === 'user' || value.role === 'jarvis' || value.role === 'inara')
    && typeof value.text === 'string' && value.text.length <= 12000 && typeof value.final === 'boolean';
}

export function createVoiceClient(socket: VoiceSocket) {
  const scope = createRpcScope(socket);
  return {
    on: scope.on,
    dispose: scope.dispose,
    async start(request: VoiceStart): Promise<VoiceStartResult> {
      const result = await scope.call<VoiceStartResult>('voice_start', request, 10000);
      if (typeof result.session_id !== 'string' || !UUID.test(result.session_id) || result.input_rate !== 16000 || result.output_rate !== 24000)
        throw new RpcError('Voice returned an invalid session. Try again.', 'invalid_response', true);
      return result;
    },
    stop(request: VoiceReference) {
      return scope.call('voice_stop', request, 5000);
    },
    /** Fire-and-forget: the core answers failures with voice_state. */
    activity(request: VoiceActivity) {
      if (socket.connected) socket.emit('voice_activity', request);
    },
    audio(frame: VoiceAudio) {
      if (socket.connected) socket.emit('voice_audio', frame);
    },
  };
}
