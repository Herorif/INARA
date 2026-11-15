import React, { useEffect, useState } from 'react';
import { Brain, X } from 'lucide-react';
import socket from '../../services/socket';
import { REMEMBERED_MS, rememberedText } from './memoryModel';
import './memory.css';

/**
 * "Remembered: <text>" when the core sends memory_remembered (the brain's memory_remember).
 * The app has no toast system, so this is a short-lived workspace banner; it leaves on its
 * own after a few seconds or with its close button.
 */
export default function RememberedNotice() {
  const [text, setText] = useState(null);
  useEffect(() => {
    const handle = payload => { const value = rememberedText(payload); if (value) setText({ value, at: Date.now() }); };
    socket.on('memory_remembered', handle);
    return () => { socket.off('memory_remembered', handle); };
  }, []);
  useEffect(() => {
    if (!text) return undefined;
    const timer = setTimeout(() => setText(null), REMEMBERED_MS);
    return () => clearTimeout(timer);
  }, [text]);
  if (!text) return null;
  return <div role="status" className="system-banner system-banner--accent remembered-notice">
    <Brain size={16} aria-hidden="true" />
    <span className="remembered-notice__text">{text.value}</span>
    <button type="button" className="btn btn--ghost btn--icon btn--sm system-banner__action" aria-label="Dismiss" onClick={() => setText(null)}><X size={14} aria-hidden="true" /></button>
  </div>;
}
