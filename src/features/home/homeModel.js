// Home Assistant (docs/HOME_ASSISTANT.md): the Connections card and the Home view. Pure: the
// components render what cardView, homeView and tileView return. The core is the authority
// (backend/services/home_assistant.py): it sends `home_status` {connected, url, host,
// insecure, devices, rooms, grouped_by, legacy_token_ignored, last_error}; the token never
// reaches the renderer after Connect.

export const INTRO =
  'Lets JARVIS see and control the lights, switches, fans, climate and other devices in your Home Assistant. The token stays encrypted on this PC.';
export const URL_PLACEHOLDER = 'http://homeassistant.local:8123';
export const HTTP_NOTE = "This address isn't encrypted; use it only on your home network.";
export const LEGACY_NOTE = 'An old token in settings was ignored; paste it again here to store it encrypted.';
export const TOKEN_HELP = 'How to get a token';
export const TOKEN_STEPS = [
  'In Home Assistant, open your profile.',
  'Open the Security tab.',
  'Under Long-lived access tokens, select Create token and name it JARVIS.',
  'Copy the token and paste it here.',
];
export const EMPTY_TITLE = "Home Assistant isn't connected";
export const EMPTY_BODY = 'Connect it to see and control your rooms here.';
export const EMPTY_ACTION = 'Connect Home Assistant';

export const ACCESS_OPTIONS = [
  { id: 'can', label: 'JARVIS can control' },
  { id: 'ask', label: 'Always asks' },
  { id: 'off', label: 'Off limits' },
];
// Tones map to text-2, warn and danger.
export const ACCESS_LABELS = {
  can: { text: 'JARVIS can control', tone: 'normal' },
  ask: { text: 'Always asks', tone: 'warn' },
  off: { text: 'Off limits', tone: 'danger' },
};
export const DOMAINS = [
  'light', 'switch', 'input_boolean', 'fan', 'cover', 'climate', 'media_player', 'lock',
  'alarm_control_panel', 'scene', 'script',
];

const ENTITY_ID = /^[a-z0-9_]{1,64}\.[a-z0-9_]{1,190}$/;
const text = (value, limit = 120) => (typeof value === 'string' ? value.slice(0, limit) : '');
const count = (value) => (Number.isSafeInteger(value) && value >= 0 ? value : null);
const number = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** A validated status, or null for anything the core would never send. */
export function normalizeStatus(raw) {
  if (!raw || typeof raw !== 'object' || typeof raw.connected !== 'boolean') return null;
  const error = raw.last_error && typeof raw.last_error === 'object'
    && typeof raw.last_error.code === 'string' && typeof raw.last_error.message === 'string'
    ? { code: raw.last_error.code, message: raw.last_error.message.slice(0, 300) }
    : null;
  return {
    connected: raw.connected,
    url: text(raw.url, 300) || null,
    host: text(raw.host, 253) || null,
    insecure: raw.insecure === true,
    devices: count(raw.devices),
    rooms: count(raw.rooms),
    groupedBy: raw.grouped_by === 'area' || raw.grouped_by === 'domain' ? raw.grouped_by : null,
    legacyTokenIgnored: raw.legacy_token_ignored === true,
    error,
  };
}

/** "11 devices in 3 rooms" ("11 devices" when there are no rooms). */
export function countText(devices, rooms) {
  const base = `${devices} device${devices === 1 ? '' : 's'}`;
  return rooms ? `${base} in ${rooms} room${rooms === 1 ? '' : 's'}` : base;
}

/** "Connected to homeassistant.local · 11 devices in 3 rooms". */
export function connectedLine(status) {
  if (!status?.connected) return null;
  const host = status.host || 'Home Assistant';
  return status.devices === null ? `Connected to ${host}` : `Connected to ${host} · ${countText(status.devices, status.rooms)}`;
}

/** True when the typed address uses plain http (the card then shows HTTP_NOTE). */
export function isInsecureAddress(value) {
  return typeof value === 'string' && /^\s*http:\/\//i.test(value);
}

/** Both fields are needed before Connect. */
export function connectReady(url, token) {
  return typeof url === 'string' && url.trim().length > 0 && typeof token === 'string' && token.trim().length > 0;
}

/**
 * What the Connections card shows. `status` is normalizeStatus output (or null while
 * loading); `ui` is {busy, error, online, url}.
 */
export function cardView(status, ui = {}) {
  const online = ui.online !== false;
  const busy = !!ui.busy;
  const localError = typeof ui.error === 'string' && ui.error ? ui.error : '';
  const connected = !!status?.connected;
  return {
    phase: !status ? 'loading' : connected ? 'connected' : 'ready',
    chip: connected ? { label: 'Connected', tone: 'ok' } : { label: 'Not connected', tone: 'idle' },
    intro: connected ? null : INTRO,
    legacy: status?.legacyTokenIgnored ? LEGACY_NOTE : null,
    form: !connected,
    httpNote: !connected && isInsecureAddress(ui.url) ? HTTP_NOTE : null,
    error: localError || (connected ? status?.error?.message || '' : ''),
    account: connected ? connectedLine(status) : null,
    connect: connected ? null : {
      label: busy ? 'Connecting…' : 'Connect',
      disabled: !status || !online || busy || !connectReady(ui.url, ui.token),
    },
    disconnect: connected ? { label: 'Disconnect', disabled: !online || busy } : null,
  };
}

/** One device from the core, or null. */
export function normalizeDevice(raw) {
  if (!raw || typeof raw !== 'object' || typeof raw.entity_id !== 'string' || !ENTITY_ID.test(raw.entity_id)) return null;
  if (!DOMAINS.includes(raw.domain) || !['can', 'ask', 'off'].includes(raw.access)) return null;
  const climate = raw.climate && typeof raw.climate === 'object' ? {
    target: number(raw.climate.target), current: number(raw.climate.current),
    unit: raw.climate.unit === '°F' ? '°F' : '°C', mode: text(raw.climate.mode, 40),
  } : null;
  const brightness = number(raw.brightness);
  return {
    entityId: raw.entity_id,
    name: text(raw.name, 80) || raw.entity_id,
    domain: raw.domain,
    room: text(raw.room, 80) || 'Other',
    state: text(raw.state, 40),
    stateText: text(raw.state_text, 60),
    available: raw.available !== false,
    access: raw.access,
    toggle: raw.toggle === true,
    on: typeof raw.on === 'boolean' ? raw.on : null,
    dimmable: raw.dimmable === true,
    brightness: brightness === null ? null : Math.max(0, Math.min(100, Math.round(brightness))),
    climate,
  };
}

/** {devices, rooms, groupedBy} from a home_devices reply, or null. */
export function normalizeDevices(raw) {
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.devices)) return null;
  const devices = raw.devices.map(normalizeDevice).filter(Boolean);
  const rooms = Array.isArray(raw.rooms) ? raw.rooms.filter((room) => typeof room === 'string' && room).map((room) => room.slice(0, 80)) : [];
  return { devices, rooms, groupedBy: raw.grouped_by === 'domain' ? 'domain' : 'area' };
}

/** A tile: icon key, name, state line and the controls the design shows for its kind. */
export function tileView(device, ui = {}) {
  const busy = !!ui.busy;
  const switchable = device.toggle && device.available;
  return {
    id: device.entityId,
    icon: device.domain,
    name: device.name,
    stateText: device.stateText,
    toggle: switchable ? {
      on: !!device.on, label: `${device.on ? 'Turn off' : 'Turn on'} ${device.name}`, disabled: busy || ui.online === false,
    } : null,
    brightness: device.domain === 'light' && device.dimmable && device.on && device.available ? {
      value: device.brightness ?? 100, label: `${device.name} brightness`, disabled: busy || ui.online === false,
    } : null,
    climate: device.domain === 'climate' && device.climate ? {
      setPoint: device.climate.target === null ? null : `${device.climate.target} ${device.climate.unit}`,
      mode: device.climate.mode || null,
    } : null,
    access: { ...ACCESS_LABELS[device.access], value: device.access },
    menuLabel: `JARVIS access for ${device.name}`,
  };
}

/**
 * The Home view. `status` is normalizeStatus output, `list` normalizeDevices output (or
 * null before the first load); `ui` is {busy, error, online, pending: {entityId: true}}.
 */
export function homeView(status, list, ui = {}) {
  const connected = !!status?.connected;
  const pending = ui.pending || {};
  if (!connected) {
    return {
      connected: false, line: null, refresh: null, rooms: [], loading: false,
      empty: status ? { title: EMPTY_TITLE, body: EMPTY_BODY, action: EMPTY_ACTION } : null,
      error: typeof ui.error === 'string' ? ui.error : '',
    };
  }
  const rooms = [];
  if (list) {
    const byRoom = new Map(list.rooms.map((room) => [room, []]));
    for (const device of list.devices) {
      if (!byRoom.has(device.room)) byRoom.set(device.room, []);
      byRoom.get(device.room).push(tileView(device, { busy: !!pending[device.entityId], online: ui.online }));
    }
    for (const [name, tiles] of byRoom) if (tiles.length) rooms.push({ name, tiles });
  }
  return {
    connected: true,
    line: connectedLine(status),
    refresh: { label: ui.busy ? 'Refreshing' : 'Refresh', disabled: !!ui.busy || ui.online === false },
    rooms,
    loading: !list && !!ui.busy,
    empty: null,
    error: (typeof ui.error === 'string' && ui.error) || status.error?.message || '',
  };
}

/** The list with one device replaced (after a tile control). */
export function withDevice(list, raw) {
  const device = normalizeDevice(raw);
  if (!list || !device) return list;
  return { ...list, devices: list.devices.map((item) => (item.entityId === device.entityId ? device : item)) };
}

/** The list with one device's access changed (after the tile menu). */
export function withAccess(list, entityId, access) {
  if (!list || !ACCESS_LABELS[access]) return list;
  return { ...list, devices: list.devices.map((item) => (item.entityId === entityId ? { ...item, access } : item)) };
}
