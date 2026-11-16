import React, { useEffect, useState } from 'react';
import { Monitor } from 'lucide-react';
import socket from '../../services/socket';
import { SCREEN_LOOK_MS, SCREEN_LOOK_TEXT, screenLookVisible } from './screenLookModel';

/**
 * "Looking at your screen…" while the core takes the one approved screenshot (screen_look).
 * The workspace window is left out of the screenshot itself; this banner leaves after the
 * capture or after one second, whichever comes first.
 */
export default function ScreenLookNotice() {
  const [shown, setShown] = useState(null);
  useEffect(() => {
    const handle = payload => { const value = screenLookVisible(payload); if (value !== null) setShown(value ? Date.now() : null); };
    socket.on('screen_look', handle);
    return () => { socket.off('screen_look', handle); };
  }, []);
  useEffect(() => {
    if (!shown) return undefined;
    const timer = setTimeout(() => setShown(null), SCREEN_LOOK_MS);
    return () => clearTimeout(timer);
  }, [shown]);
  if (!shown) return null;
  return <div role="status" className="system-banner system-banner--accent">
    <Monitor size={16} aria-hidden="true" />
    <span>{SCREEN_LOOK_TEXT}</span>
  </div>;
}
