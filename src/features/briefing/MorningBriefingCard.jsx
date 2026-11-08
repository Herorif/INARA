import React, { useEffect, useMemo, useState } from 'react';
import { Play, X } from 'lucide-react';
import useStore from '../../store';
import socket from '../../services/socket';
import HudLabel from '../../shared/ui/HudLabel';
import { createBriefingClient } from './briefingClient';
import { DISMISS_LABEL, EMPTY_TEXT, PLAY_LABEL, briefingVisible, headerText, itemLink, playMessage } from './briefingModel.js';
import './morning-briefing.css';

function Item({ item, onOpen }) {
  const link = itemLink(item);
  const store = useStore.getState;
  const text = link?.kind === 'studio'
    ? <button type="button" className="morning-briefing__text morning-briefing__text--link" title={link.title} onClick={() => onOpen?.(link.feature, undefined, link.requestId)}>{item.text}</button>
    : <span className="morning-briefing__text">{item.text}</span>;
  return <li className="morning-briefing__item" data-tone={item.tone || undefined}>
    <span className="morning-briefing__time">{item.time}</span>
    <span className="morning-briefing__body">
      {text}
      {item.detail && <span className="morning-briefing__detail">{item.detail}</span>}
      {link?.kind === 'call' && <button type="button" className="morning-briefing__link" onClick={() => store().focusCall(link.focus)}>{link.label}</button>}
    </span>
  </li>;
}

/**
 * P2: today's morning briefing at the top of the conversation, under the presence header.
 * "Play again" composes and speaks it now; Dismiss hides it for today. "Call back" opens Calls
 * on that record with its callback approval focused (never a call by itself); a finished job
 * opens its revision in the studio.
 */
export default function MorningBriefingCard({ onOpen }) {
  const briefing = useStore(state => state.briefing);
  const connected = useStore(state => state.backendConnected);
  const client = useMemo(() => createBriefingClient(socket), []);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => () => client.dispose(), [client]);
  useEffect(() => { setNow(Date.now()); setMessage(''); }, [briefing]);
  // Hidden at its expiry (12:00 local) even if the core's clear arrives later.
  useEffect(() => {
    if (!briefing) return undefined;
    const timer = setTimeout(() => setNow(Date.now()), Math.max(0, briefing.expiresAt - Date.now()) + 50);
    return () => clearTimeout(timer);
  }, [briefing]);

  if (!briefingVisible(briefing, now)) return null;

  const play = async () => {
    setBusy(true);
    setMessage('');
    try { setMessage(playMessage(await client.play())); }
    catch (error) { setMessage(playMessage(error)); }
    finally { setBusy(false); }
  };
  const dismiss = () => {
    useStore.setState({ briefing: null });
    client.dismiss().catch(() => {});
  };

  return <div className="conversation-briefing"><section className="morning-briefing" aria-labelledby="morning-briefing-title" data-briefing={briefing.date}>
    <header className="morning-briefing__header">
      <HudLabel as="h3" id="morning-briefing-title" className="morning-briefing__title">{headerText(briefing)}</HudLabel>
      <div className="morning-briefing__actions">
        <button type="button" className="btn btn--ghost btn--sm" disabled={!connected || busy} onClick={play}><Play size={14} aria-hidden="true" /><span>{PLAY_LABEL}</span></button>
        <button type="button" className="btn btn--ghost btn--icon btn--sm" aria-label={DISMISS_LABEL} title={DISMISS_LABEL} onClick={dismiss}><X size={14} aria-hidden="true" /></button>
      </div>
    </header>
    {message && <p className="morning-briefing__message" role="status">{message}</p>}
    {briefing.sections.length
      ? <div className="morning-briefing__sections">
        {briefing.sections.map(section => <div key={section.id} className="morning-briefing__section" data-section={section.id}>
          <HudLabel as="h4" className="morning-briefing__label">{section.label}</HudLabel>
          <ul className="morning-briefing__items">{section.items.map((item, index) => <Item key={index} item={item} onOpen={onOpen} />)}</ul>
        </div>)}
      </div>
      : <p className="morning-briefing__empty">{EMPTY_TEXT}</p>}
  </section></div>;
}
