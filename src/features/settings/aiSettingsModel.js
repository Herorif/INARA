// Pure mappings for the "AI and assistant" Preferences section: key status -> chip,
// provider check / RPC failure -> plain result message, brain snapshot -> helper text.
// No values ever pass through here; only the status objects the core returns.

export const PROVIDERS = [
  { name: 'anthropic_api_key', title: 'Anthropic', provider: 'Anthropic', purpose: 'Brain: chat, planning and tools' },
  { name: 'gemini_api_key', title: 'Google Gemini', provider: 'Google', purpose: 'Transcription and voice' },
];

export const BRAIN_OPTIONS = [
  { id: 'auto', label: 'Auto' },
  { id: 'claude', label: 'Claude' },
  { id: 'gemini', label: 'Gemini' },
];

export const ENV_NOTE = 'Set by a developer environment variable';
export const REMOVE_CONFIRM = 'Remove this key? JARVIS will stop using it.';
export const AUTO_HELP = 'Claude when an Anthropic key is set, otherwise Gemini.';
export const NAME_HELP = 'JARVIS uses it sparingly.';
export const CLAUDE_WITHOUT_KEY = 'The assistant is set to use Claude, but no Anthropic API key is saved. Add one under AI providers, or choose Auto.';

// Other stored secrets that share the key row (Calls setup and settings).
const OTHER_PROVIDERS = {
  twilio_account_sid: 'Twilio', twilio_auth_token: 'Twilio', twilio_phone_number: 'Twilio',
  owner_phone_number: 'Twilio', cloudflare_tunnel_token: 'Cloudflare', call_briefing_pin: 'JARVIS',
};

export function providerFor(name) {
  return PROVIDERS.find(entry => entry.name === name)?.provider ?? OTHER_PROVIDERS[name] ?? 'the provider';
}

/** Chip for one key status: { tone, label, envOverride }. */
export function secretChip(status) {
  if (!status || !status.configured) return { tone: 'idle', label: 'NOT SET', envOverride: false };
  if (status.source === 'env') return { tone: 'accent', label: 'ENV OVERRIDE', envOverride: true };
  const check = status.last_check;
  // Values with nothing to check against (phone numbers, tunnel token, PIN) are simply saved.
  if (check && check.code === 'no_check') {
    return status.hint ? { tone: 'ok', label: `SAVED ··${status.hint}`, envOverride: false, hint: status.hint, prefix: 'SAVED' } : { tone: 'ok', label: 'SAVED', envOverride: false };
  }
  if (check && check.code === 'invalid_key') return { tone: 'danger', label: 'REJECTED', envOverride: false };
  if ((check && check.ok) || (!check && status.verified_at)) {
    // hint: last four characters, rendered without the chip's uppercase transform.
    return { tone: 'ok', label: status.hint ? `VERIFIED ··${status.hint}` : 'VERIFIED', envOverride: false, hint: status.hint || null };
  }
  return { tone: 'warn', label: 'SAVED · NOT VERIFIED', envOverride: false };
}

/** Plain sentence for a transport failure (no Studio/revision wording from the shared RPC scope). */
export function rpcFailureMessage(error) {
  const code = error && typeof error === 'object' ? error.code : undefined;
  if (code === 'offline' || code === 'disconnected') return 'JARVIS core is offline. Reconnect and try again.';
  if (code === 'timeout') return 'The core did not answer in time. Check the key status before trying again.';
  if (code === 'invalid_response' || code === 'send_failed' || code === 'scope_closed') return 'The request did not finish. Reopen Preferences and try again.';
  const message = error && typeof error === 'object' && typeof error.message === 'string' ? error.message : '';
  return message || 'The request did not finish. Try again.';
}

/** Message after Save; `status` is the stored key's status (secrets_set with verify). */
export function saveResultMessage(name, status) {
  if (status?.last_check?.ok) return { tone: 'ok', text: 'Key saved and verified.' };
  if (status?.last_check?.code === 'no_check') return { tone: 'ok', text: 'Saved.' };
  if (status?.last_check?.code === 'incomplete') return { tone: 'warn', text: `Saved. ${providerFor(name)} can check it once the other value is saved.` };
  return { tone: 'warn', text: "Couldn't reach the service — the key was saved but not verified." };
}

/** Message when the provider rejected the key; the core stored nothing. */
export function rejectedMessage(name, hadPrevious) {
  const provider = providerFor(name);
  return {
    tone: 'danger',
    text: `This key was rejected by ${provider}. ${hadPrevious ? 'Your previous key was kept.' : 'It was not saved.'}`,
  };
}

/** Message after the Test button (mirrors backend CHECK_MESSAGES). */
export function testResultMessage(name, status) {
  const provider = providerFor(name);
  const code = status?.last_check?.code;
  if (status?.last_check?.ok) return { tone: 'ok', text: `${provider} accepted this key.` };
  if (code === 'invalid_key') return { tone: 'danger', text: `This key was rejected by ${provider}.` };
  if (code === 'incomplete') return { tone: 'warn', text: `Save the other ${provider} value first, then test again.` };
  if (code === 'network_error') return { tone: 'warn', text: "Couldn't reach the service. Check your connection." };
  if (code === 'tls_error') return { tone: 'warn', text: "Couldn't make a secure connection to the service. A proxy or antivirus may be intercepting HTTPS." };
  if (code === 'rate_limited') return { tone: 'warn', text: `${provider} is limiting requests right now. Try the test again in a minute.` };
  return { tone: 'warn', text: `${provider} gave an unexpected answer. Try again later.` };
}

/** "Active model: …" line from the capability snapshot's brain object. */
export function activeModelText(brain) {
  if (!brain || typeof brain !== 'object') return '';
  const label = brain.label || brain.model || 'unknown';
  if (!brain.configured) return `Active model: ${label} (not configured)`;
  if (brain.provider === 'gemini' && brain.setting === 'auto') return `Active model: ${label} (fallback)`;
  return `Active model: ${label}`;
}

/** Inline problem for the chosen brain, or '' when it can run. */
export function brainProblem(setting, brain) {
  if (setting === 'claude' && brain && brain.provider === 'claude' && !brain.configured) return CLAUDE_WITHOUT_KEY;
  return '';
}

export function brainOption(assistant) {
  const value = assistant && typeof assistant === 'object' ? assistant.brain : undefined;
  return BRAIN_OPTIONS.some(entry => entry.id === value) ? value : 'auto';
}

// assistant.address: how JARVIS addresses the owner (backend services/conversation.persona).
export const ADDRESS_LABEL = 'How JARVIS addresses you';
export const ADDRESS_OPTIONS = [
  { id: 'sir', label: 'Sir' },
  { id: 'maam', label: "Ma'am" },
  { id: 'name', label: 'By name' },
  { id: 'none', label: 'None' },
];
export const ADDRESS_NAME_HINT = 'Add your name above to be addressed by name.';

/** The saved form of address; 'sir' when missing or unknown, as the core reads it. */
export function addressOption(assistant) {
  const value = assistant && typeof assistant === 'object' ? assistant.address : undefined;
  return ADDRESS_OPTIONS.some(entry => entry.id === value) ? value : 'sir';
}

/** Hint under the control: "By name" with no saved name has nothing to address the owner by. */
export function addressHint(address, savedName) {
  const named = typeof savedName === 'string' && savedName.trim() !== '';
  return address === 'name' && !named ? ADDRESS_NAME_HINT : '';
}
