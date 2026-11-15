// Pure mappings for the "AI and assistant" Preferences section: key status -> chip,
// provider check / RPC failure -> plain result message, brain snapshot -> helper text.
// No values ever pass through here; only the status objects the core returns.

export const PROVIDERS = [
  { name: 'anthropic_api_key', title: 'Anthropic', provider: 'Anthropic', purpose: 'Brain: chat, planning and tools' },
  { name: 'gemini_api_key', title: 'Google Gemini', provider: 'Google', purpose: 'Transcription and voice' },
];

// assistant.brain values the core accepts (backend llm/router.py BRAIN_SETTINGS).
const BRAIN_SETTINGS = ['auto', 'claude', 'gemini'];
export const SONNET = 'claude-sonnet-5-5';
export const HAIKU = 'claude-haiku-5-5';

// The "Brain" select: one choice per brain/model pair (S2).
export const BRAIN_LABEL = 'Brain';
export const BRAIN_CHOICES = [
  { id: 'auto', label: 'Auto (Claude when a key is set)' },
  { id: 'sonnet', label: 'Claude Sonnet 5.5 — smartest' },
  { id: 'haiku', label: 'Claude Haiku 5.5 — fastest, cheapest' },
  { id: 'gemini', label: 'Gemini' },
];
const CHOICE_PATCH = {
  auto: { brain: 'auto' },
  sonnet: { brain: 'claude', claude_model: SONNET },
  haiku: { brain: 'claude', claude_model: HAIKU },
  gemini: { brain: 'gemini' },
};

export const GEMINI_MODEL_LABEL = 'Gemini model';
export const GEMINI_LIST_FAILED = "Couldn't load the model list.";

// assistant.effort: Claude's output_config.effort (xhigh/max left out on purpose).
export const EFFORT_LABEL = 'Effort';
export const EFFORT_OPTIONS = [
  { id: 'low', label: 'Low' },
  { id: 'medium', label: 'Medium' },
  { id: 'high', label: 'High' },
];
export const EFFORT_HELP = 'Higher effort thinks longer and costs more. Medium suits most requests.';
export const EFFORT_GEMINI_HELP = 'Gemini manages its own thinking.';

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

const assistantOf = (assistant) => (assistant && typeof assistant === 'object' ? assistant : {});
const geminiId = (value) => (typeof value === 'string' && value.trim().startsWith('gemini-') ? value.trim() : '');

/** The saved effort; 'medium' when missing or stale, as the core reads it. */
export function effortOption(assistant) {
  const value = assistantOf(assistant).effort;
  return EFFORT_OPTIONS.some(entry => entry.id === value) ? value : 'medium';
}

const effortLabel = (effort) => (EFFORT_OPTIONS.find(entry => entry.id === effort) || EFFORT_OPTIONS[1]).label;

/**
 * "Using …" line from the capability snapshot's brain object: Claude with its effort,
 * Gemini with its model id. `assistant` (saved settings) supplies the effort when the
 * snapshot has none.
 */
export function activeModelText(brain, assistant) {
  if (!brain || typeof brain !== 'object') return '';
  let text;
  if (brain.provider === 'gemini') {
    const model = geminiId(brain.model) || geminiId(brain.gemini_model);
    text = model ? `Using Gemini (${model})` : 'Using Gemini';
  } else {
    const effort = EFFORT_OPTIONS.some(entry => entry.id === brain.effort) ? brain.effort : effortOption(assistant);
    text = `Using ${brain.label || brain.model || 'Claude'} · ${effortLabel(effort)} effort`;
  }
  if (!brain.configured) return `${text} (not configured)`;
  if (brain.provider === 'gemini' && brain.setting === 'auto') return `${text} (fallback)`;
  return text;
}

/** Inline problem for the chosen brain, or '' when it can run. */
export function brainProblem(setting, brain) {
  if (setting === 'claude' && brain && brain.provider === 'claude' && !brain.configured) return CLAUDE_WITHOUT_KEY;
  return '';
}

export function brainOption(assistant) {
  const value = assistantOf(assistant).brain;
  return BRAIN_SETTINGS.includes(value) ? value : 'auto';
}

/** The "Brain" select's choice for the saved settings (a stale Claude model reads as Sonnet). */
export function brainChoice(assistant) {
  const setting = brainOption(assistant);
  if (setting === 'claude') return assistantOf(assistant).claude_model === HAIKU ? 'haiku' : 'sonnet';
  return setting;
}

/** The settings patch for picking `choice`, or null when nothing changes. Auto keeps claude_model. */
export function brainChoicePatch(choice, assistant) {
  if (!CHOICE_PATCH[choice] || choice === brainChoice(assistant)) return null;
  return { assistant: { ...CHOICE_PATCH[choice] } };
}

/**
 * True when the chosen brain resolves to Gemini, where effort does not apply: brain=gemini,
 * or Auto with the snapshot on Gemini (no Anthropic key). Before the snapshot loads, Auto
 * falls back to the key status (`anthropicConfigured`: true, false or unknown).
 */
export function effortDisabled(setting, brain, anthropicConfigured) {
  if (setting === 'gemini') return true;
  if (setting !== 'auto') return false;
  if (brain && typeof brain === 'object' && typeof brain.provider === 'string') return brain.provider === 'gemini';
  return anthropicConfigured === false;
}

/** Helper line under the Effort control. */
export function effortHelp(disabled) {
  return disabled ? EFFORT_GEMINI_HELP : EFFORT_HELP;
}

/** The effort patch, or null when it is already saved or not a known effort. */
export function effortPatch(next, assistant) {
  if (!EFFORT_OPTIONS.some(entry => entry.id === next) || next === effortOption(assistant)) return null;
  return { assistant: { effort: next } };
}

/** The saved Gemini model: assistant.gemini_model, else the snapshot's, else ''. */
export function geminiModelValue(assistant, brain) {
  const saved = geminiId(assistantOf(assistant).gemini_model);
  if (saved) return saved;
  if (!brain || typeof brain !== 'object') return '';
  return geminiId(brain.gemini_model) || (brain.provider === 'gemini' ? geminiId(brain.model) : '');
}

/**
 * <select> options for the Gemini model: the fetched list (or nothing before it loads or when
 * it failed), with the saved value added first when the list does not carry it.
 */
export function geminiModelOptions(list, saved) {
  const options = [];
  for (const entry of Array.isArray(list) ? list : []) {
    const id = entry && typeof entry === 'object' ? geminiId(entry.id) : '';
    if (!id || options.some(option => option.value === id)) continue;
    options.push({ value: id, label: typeof entry.label === 'string' && entry.label.trim() ? entry.label.trim() : id });
  }
  const current = geminiId(saved);
  if (current && !options.some(option => option.value === current)) options.unshift({ value: current, label: current });
  return options;
}

/** The gemini_model patch, or null when it is already saved or not a Gemini id. */
export function geminiModelPatch(next, saved) {
  const id = geminiId(next);
  if (!id || id === geminiId(saved)) return null;
  return { assistant: { gemini_model: id } };
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

// assistant.home_place: the owner's home town for weather (docs/WEATHER.md).
export const HOME_PLACE_LABEL = 'Home town';
export const HOME_PLACE_PLACEHOLDER = 'e.g. Kuala Lumpur';
export const HOME_PLACE_HELP = "Used for weather when you don't name a place.";
export const HOME_PLACE_UNSET = 'Not set';
export const HOME_PLACE_EMPTY = 'Type a town or city first.';
export const HOME_PLACE_MAX = 120;

/** The saved home town's name ("Kuala Lumpur, Malaysia"), or '' when unset or malformed. */
export function homePlaceName(assistant) {
  const place = assistant && typeof assistant === 'object' ? assistant.home_place : null;
  if (!place || typeof place !== 'object' || typeof place.name !== 'string') return '';
  if (!Number.isFinite(place.lat) || !Number.isFinite(place.lon)) return '';
  return place.name.trim();
}

/** Status line under the Home town row. */
export function homePlaceStatus(assistant) {
  return homePlaceName(assistant) || HOME_PLACE_UNSET;
}

/** The typed town with spaces collapsed, or '' when there is nothing to save. */
export function homePlaceInput(raw) {
  return typeof raw === 'string' ? raw.replace(/\s+/g, ' ').trim().slice(0, HOME_PLACE_MAX) : '';
}

/** Hint under the control: "By name" with no saved name has nothing to address the owner by. */
export function addressHint(address, savedName) {
  const named = typeof savedName === 'string' && savedName.trim() !== '';
  return address === 'name' && !named ? ADDRESS_NAME_HINT : '';
}

// "Run a check" under the Brain row (brain_check, S1.7): one short test message through
// the chat route and a weather lookup for the home town, each timed by the core.
export const BRAIN_CHECK_LABEL = 'Check the brain';
export const BRAIN_CHECK_HELP = 'Sends one short test message and a weather lookup, and shows how long each took.';
export const BRAIN_CHECK_BUTTON = 'Run a check';
export const BRAIN_CHECK_BUSY = 'Checking…';
const BRAIN_CHECK_FAILED = "The brain didn't answer. Try again.";
const WEATHER_CHECK_FAILED = "The weather lookup didn't finish. Try again.";

/** "1.8 s" from milliseconds; "under 0.1 s" below 100 ms; '' when unknown. */
export function checkSeconds(ms) {
  if (!Number.isFinite(ms) || ms < 0) return '';
  if (ms < 100) return 'under 0.1 s';
  return `${(ms / 1000).toFixed(1)} s`;
}

const plain = (value) => (typeof value === 'string' && value.trim() ? value.trim() : '');
const inTime = (ms) => { const time = checkSeconds(ms); return time ? ` in ${time}` : ''; };

/** The brain half's line: "Claude Sonnet 5.5 · Medium effort answered in 1.8 s", or the core's message. */
export function brainCheckLine(brain) {
  if (!brain || typeof brain !== 'object') return { tone: 'warn', text: BRAIN_CHECK_FAILED };
  if (!brain.ok) return { tone: 'warn', text: plain(brain.message) || BRAIN_CHECK_FAILED };
  const name = plain(brain.label) || plain(brain.model) || 'The brain';
  const effort = EFFORT_OPTIONS.find(entry => entry.id === brain.effort);
  return { tone: 'ok', text: `${name}${effort ? ` · ${effort.label} effort` : ''} answered${inTime(brain.ms)}` };
}

/** The weather half's line: "Weather for Kuala Lumpur, Malaysia in 0.4 s", the skip note, or the core's message. */
export function weatherCheckLine(weather) {
  if (!weather || typeof weather !== 'object') return { tone: 'warn', text: WEATHER_CHECK_FAILED };
  if (weather.skipped) return { tone: 'idle', text: plain(weather.message) || 'Set your home town to include a weather check.' };
  if (!weather.ok) return { tone: 'warn', text: plain(weather.message) || WEATHER_CHECK_FAILED };
  const place = plain(weather.place);
  return { tone: 'ok', text: `Weather${place ? ` for ${place}` : ''}${inTime(weather.ms)}` };
}

/** Both result lines for a brain_check answer ({ brain, weather }). */
export function brainCheckLines(result) {
  return [brainCheckLine(result?.brain), weatherCheckLine(result?.weather)];
}
