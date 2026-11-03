// Owner presence for call briefings (C3): the core phones the owner with urgent briefings
// only when they are away from the PC. The workspace tells it they are here with
// `presence_ping` on user input (at most once a minute) and whenever the window gains focus.

export const PRESENCE_INTERVAL_MS = 60000;
const INPUT_EVENTS = ['keydown', 'pointerdown', 'wheel'];

/**
 * Starts listening at once; returns stop(). `target` receives the input and focus events,
 * `hasFocus` says whether the workspace window is focused, `now` is the clock.
 */
export function startPresencePing({ socket, target = window, hasFocus = () => document.hasFocus(), now = () => Date.now(), interval = PRESENCE_INTERVAL_MS }) {
  let last = -Infinity;
  const send = () => {
    if (!socket.connected) return;
    last = now();
    try { socket.emit('presence_ping', {}, () => {}); } catch { /* the next input tries again */ }
  };
  const onInput = () => { if (hasFocus() && now() - last >= interval) send(); };
  const onFocus = () => send();
  const options = { passive: true, capture: true };
  INPUT_EVENTS.forEach(name => target.addEventListener(name, onInput, options));
  target.addEventListener('focus', onFocus);
  return () => {
    INPUT_EVENTS.forEach(name => target.removeEventListener(name, onInput, options));
    target.removeEventListener('focus', onFocus);
  };
}
