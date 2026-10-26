// Discovered printer hosts are untrusted. Only build a web-interface URL for a
// private-LAN IPv4 address (RFC 1918) or a local hostname.

const OCTET = /^(?:0|[1-9]\d{0,2})$/;
const LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const LOCAL_SUFFIXES = ['local', 'lan', 'home', 'internal', 'home.arpa'];

function privateIPv4(host) {
  const parts = host.split('.');
  if (parts.length !== 4 || !parts.every(part => OCTET.test(part))) return false;
  const [a, b] = parts.map(Number);
  if (parts.some(part => Number(part) > 255)) return false;
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

function localHostname(host) {
  if (host.length > 253 || host === 'localhost') return false;
  const labels = host.split('.');
  if (!labels.every(label => LABEL.test(label))) return false;
  if (labels.length === 1) return !/^\d+$/.test(host);
  return LOCAL_SUFFIXES.some(suffix => host.endsWith(`.${suffix}`) && host.length > suffix.length + 1);
}

/** Normalized host when it is safe to open, otherwise null. */
export function privateLanHost(host) {
  if (typeof host !== 'string') return null;
  const value = host.trim().toLowerCase();
  if (!value) return null;
  if (/^[\d.]+$/.test(value)) return privateIPv4(value) ? value : null;
  return localHostname(value) ? value : null;
}

/** http URL for a printer's web interface, or null when the host is not private-LAN. */
export function printerWebUrl(host) {
  const safe = privateLanHost(host);
  return safe ? `http://${safe}` : null;
}
