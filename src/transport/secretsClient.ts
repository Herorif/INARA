import { createRpcScope, RpcError, type RpcSocket } from './rpc.ts';

export type SecretName = 'anthropic_api_key' | 'gemini_api_key'
  | 'twilio_account_sid' | 'twilio_auth_token' | 'twilio_phone_number' | 'owner_phone_number'
  | 'cloudflare_tunnel_token' | 'call_briefing_pin';
export type SecretCheck = { ok: boolean; code: string; at: string; message?: string };
export type SecretStatus = {
  name: SecretName;
  label: string;
  configured: boolean;
  source: 'env' | 'store' | null;
  hint: string | null;
  verified_at: string | null;
  last_check: SecretCheck | null;
};
export type BrainStatus = {
  setting: 'auto' | 'claude' | 'gemini';
  provider: 'claude' | 'gemini';
  model: string;
  label: string | null;
  configured: boolean;
};

// The provider check makes one outbound request with a 10 s budget on the core.
const TEST_TIMEOUT = 25000;
// A voice preview is one TTS request with a 30 s budget on the core.
const PREVIEW_TIMEOUT = 40000;
// About 20 s of 48 kHz PCM16, base64-encoded.
const PREVIEW_LIMIT = 2_600_000;

// weather_home_set makes one geocoding request with a 9 s budget on the core.
const HOME_PLACE_TIMEOUT = 15000;
export type HomePlace = { name: string; lat: number; lon: number };
const isHomePlace = (value: unknown): value is HomePlace => {
  const place = value as HomePlace;
  return !!place && typeof place === 'object' && typeof place.name === 'string'
    && Number.isFinite(place.lat) && Number.isFinite(place.lon);
};

export type VoicePreview = { name: string; cached: boolean; sample_rate: number; pcm_base64: string };
export const isVoicePreview = (value: unknown): value is VoicePreview => {
  const preview = value as VoicePreview;
  return !!preview && typeof preview === 'object' && typeof preview.name === 'string'
    && Number.isInteger(preview.sample_rate) && preview.sample_rate >= 8000 && preview.sample_rate <= 48000
    && typeof preview.pcm_base64 === 'string' && preview.pcm_base64.length > 0 && preview.pcm_base64.length <= PREVIEW_LIMIT
    && /^[A-Za-z0-9+/]+={0,2}$/.test(preview.pcm_base64);
};

const isCheck = (value: unknown): value is SecretCheck => {
  const check = value as SecretCheck;
  return !!check && typeof check === 'object' && typeof check.ok === 'boolean' && typeof check.code === 'string';
};
const isStatus = (value: unknown): value is SecretStatus => {
  const status = value as SecretStatus;
  return !!status && typeof status === 'object' && typeof status.name === 'string' && typeof status.label === 'string'
    && typeof status.configured === 'boolean' && [null, 'env', 'store'].includes(status.source as string)
    && (status.hint === null || typeof status.hint === 'string')
    && (status.last_check === null || status.last_check === undefined || isCheck(status.last_check));
};
const invalid = () => new RpcError('The core returned an incomplete key status. Reopen Preferences to try again.', 'invalid_response');

/**
 * Owner-only API key RPCs. Values only travel renderer -> core inside `set`; every
 * response carries status (label, source, last four characters, check), never a value.
 */
export function createSecretsClient(socket: RpcSocket) {
  const scope = createRpcScope(socket);
  const one = async (event: string, data: Record<string, unknown>, timeout?: number) => {
    const response = await scope.call<{ secret?: unknown }>(event, data, timeout);
    if (!isStatus(response.secret)) throw invalid();
    return response.secret;
  };
  return {
    on: scope.on,
    dispose: scope.dispose,
    async status(): Promise<SecretStatus[]> {
      const response = await scope.call<{ secrets?: unknown }>('secrets_status', {});
      if (!Array.isArray(response.secrets) || !response.secrets.every(isStatus)) throw invalid();
      return response.secrets;
    },
    /**
     * Checks the key with the provider before storing it. A rejected key fails with
     * code `key_rejected` and the previously saved key (if any) is left untouched.
     */
    set(name: SecretName, value: string): Promise<SecretStatus> {
      return one('secrets_set', { name, value, verify: true }, TEST_TIMEOUT);
    },
    test(name: SecretName): Promise<SecretStatus> {
      return one('secrets_test', { name }, TEST_TIMEOUT);
    },
    clear(name: SecretName): Promise<SecretStatus> {
      return one('secrets_clear', { name });
    },
    /** Active brain from the capability snapshot (content-free, no network on the core). */
    async brain(): Promise<BrainStatus | null> {
      const response = await scope.call<{ brain?: unknown }>('capability_diagnostics', {});
      const brain = response.brain as BrainStatus | undefined;
      return brain && typeof brain === 'object' && typeof brain.provider === 'string' ? brain : null;
    },
    /** Spoken sample of one prebuilt voice (PCM16 mono); the core caches it per voice. */
    async voicePreview(name: string): Promise<VoicePreview> {
      const response = await scope.call<Record<string, unknown>>('voice_preview', { name }, PREVIEW_TIMEOUT);
      if (!isVoicePreview(response) || response.name !== name)
        throw new RpcError('The core returned an invalid voice preview. Try again.', 'invalid_response');
      return response;
    },
    /**
     * Geocodes and saves the owner's home town for weather (assistant.home_place), or
     * clears it with null. Failures carry the core's code (not_found, weather_unavailable).
     */
    async setHomePlace(place: string | null): Promise<HomePlace | null> {
      const response = await scope.call<{ home_place?: unknown }>('weather_home_set', { place }, HOME_PLACE_TIMEOUT);
      if (response.home_place === null) return null;
      if (!isHomePlace(response.home_place))
        throw new RpcError('The core returned an invalid home town. Reopen Preferences and try again.', 'invalid_response');
      return response.home_place;
    },
    /** Settings patch with an acknowledgement; failures carry the core's code. */
    async updateSettings(patch: Record<string, unknown>): Promise<void> {
      await scope.call('update_settings', patch);
    },
  };
}
