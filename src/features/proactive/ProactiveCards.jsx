import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { X } from 'lucide-react';
import socket from '../../services/socket';
import useStore from '../../store';
import HudFrame from '../../shared/ui/HudFrame';
import Materialise from '../../shared/motion/MaterialisePresence';
import { playCue } from '../../services/sound/uiSounds.js';
import { createProactiveClient } from './proactiveClient.js';
import {
  DIGEST_TITLE, DISMISS_ALL_LABEL, DISMISS_LABEL, FOCUS_REPORT_DELAY_MS, MUTE_ERROR, MUTE_LABEL,
  cardGroupView, clockTime, digestGroups, dismissCard, dropMuted, emptyCards, muteRequest, receiveCard,
  receiveDigest, workspaceFocused,
} from './proactiveModel.js';
import './proactive.css';

const documentVisible = () => document.visibilityState === 'visible';
const hasFocus = () => typeof document.hasFocus !== 'function' || document.hasFocus();

/** Tells the core whether this window is the focused, visible workspace (proactive_focus). */
function useFocusReport(client, connected, locked) {
  const [page, setPage] = useState(() => ({ documentVisible: documentVisible(), focused: hasFocus() }));
  const sent = useRef(null);
  const focused = workspaceFocused({ connected, documentVisible: page.documentVisible, focused: page.focused, locked });
  useEffect(() => {
    const update = () => setPage({ documentVisible: documentVisible(), focused: hasFocus() });
    document.addEventListener('visibilitychange', update);
    window.addEventListener('focus', update);
    window.addEventListener('blur', update);
    return () => {
      document.removeEventListener('visibilitychange', update);
      window.removeEventListener('focus', update);
      window.removeEventListener('blur', update);
    };
  }, []);
  useEffect(() => {
    if (!connected) { sent.current = null; return undefined; }
    if (sent.current === focused) return undefined;
    const timer = setTimeout(() => {
      client.focus(focused).then(() => { sent.current = focused; }).catch(() => {});
    }, FOCUS_REPORT_DELAY_MS);
    return () => clearTimeout(timer);
  }, [client, connected, focused]);
}

function CardEntry({ entry, onDismiss, onMute, busy, single }) {
  return <li className="proactive-card__entry" data-urgency={entry.urgency}>
    {!single && <span className="proactive-card__kind">{entry.kindText}</span>}
    <p className="proactive-card__title">{entry.title}</p>
    {entry.body && <p className="proactive-card__body">{entry.body}</p>}
    <div className="proactive-card__actions">
      {single && <button type="button" className="btn btn--secondary btn--sm" onClick={() => onDismiss(entry.id)}>{DISMISS_LABEL}</button>}
      <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => onMute(entry)}>{MUTE_LABEL}</button>
      {!single && <button type="button" className="btn btn--ghost btn--icon btn--sm proactive-card__close" aria-label={`${DISMISS_LABEL}: ${entry.title}`} onClick={() => onDismiss(entry.id)}><X size={14} aria-hidden="true"/></button>}
    </div>
  </li>;
}

/**
 * S7.2 (docs/PROACTIVE.md): the proactive engine's in-app card group (focused workspace, with the
 * notify cue) and the "While you were away" digest. Also reports the window's focus to the core.
 * `hidden` (quick assistant): nothing shown, and reported as not focused.
 */
export default function ProactiveCards({ gaming = false, hidden = false }) {
  const connected = useStore(state => state.backendConnected);
  const locked = useStore(state => state.isLockScreenVisible);
  const client = useMemo(() => createProactiveClient(socket), []);
  const [cards, setCards] = useState(emptyCards);
  const [digest, setDigest] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // The quick assistant hides the cards: the core is told this window is not the workspace then.
  useFocusReport(client, connected, locked || hidden);

  useEffect(() => () => client.dispose(), [client]);
  useEffect(() => {
    const offCard = client.on('proactive_card', payload => setCards(current => {
      const { state, fresh } = receiveCard(current, payload, Date.now());
      if (fresh) playCue('notify');
      return state;
    }));
    const offDigest = client.on('proactive_digest', payload => setDigest(receiveDigest(payload)));
    return () => { offCard(); offDigest(); };
  }, [client]);
  useEffect(() => { if (locked) { setCards(emptyCards); setDigest(null); } }, [locked]);

  const dismiss = useCallback(id => setCards(current => dismissCard(current, id)), []);
  const dismissAll = useCallback(() => setCards(emptyCards), []);
  const mute = useCallback(async entry => {
    setBusy(true); setError('');
    try {
      const rule = await client.mute(muteRequest(entry));
      setCards(current => dropMuted(current, rule || entry));
    } catch { setError(MUTE_ERROR); }
    finally { setBusy(false); }
  }, [client]);
  const clearDigest = useCallback(async () => {
    setDigest(null);
    try { await client.dismissDigest(); } catch { /* the core re-sends it on reconnect */ }
  }, [client]);

  const view = cardGroupView(cards);
  const groups = digestGroups(digest);
  if (locked || hidden) return null;
  return <div className="proactive-stack" data-proactive>
    <Materialise show={!!view} gaming={gaming}>
      {view && <HudFrame as="section" className="proactive-card" role="status" aria-live="polite" aria-label="JARVIS has news" data-proactive-card>
        <div className="proactive-card__head"><span className="hud-label proactive-card__label">{view.label}</span></div>
        <ul className="proactive-card__list">
          {view.entries.map(entry => <CardEntry key={entry.id} entry={entry} single={cards.items.length === 1} busy={busy} onDismiss={dismiss} onMute={mute}/>)}
        </ul>
        {view.more > 0 && <p className="proactive-card__more">{`+${view.more} more`}</p>}
        {error && <p className="proactive-card__error" role="alert">{error}</p>}
        {cards.items.length > 1 && <div className="proactive-card__footer"><button type="button" className="btn btn--secondary btn--sm" onClick={dismissAll}>{DISMISS_ALL_LABEL}</button></div>}
      </HudFrame>}
    </Materialise>
    <Materialise show={!!digest} gaming={gaming}>
      {digest && <HudFrame as="section" className="proactive-card proactive-digest" aria-labelledby="proactive-digest-title" data-proactive-digest>
        <div className="proactive-card__head"><h2 id="proactive-digest-title" className="proactive-digest__title">{DIGEST_TITLE}</h2></div>
        <div className="proactive-digest__groups">
          {groups.map(group => <section key={group.label} className="proactive-digest__group" aria-label={group.label}>
            <span className="hud-label proactive-card__label">{group.label.toUpperCase()}</span>
            <ul className="proactive-digest__list">
              {group.items.map(item => <li key={item.id} className="proactive-digest__item">
                <span className="proactive-digest__time">{clockTime(item.at)}</span>
                <span className="proactive-digest__text"><span className="proactive-card__title">{item.title}</span>{item.body && <span className="proactive-card__body">{item.body}</span>}</span>
              </li>)}
            </ul>
          </section>)}
        </div>
        <div className="proactive-card__footer"><button type="button" className="btn btn--secondary btn--sm" onClick={clearDigest}>{DISMISS_ALL_LABEL}</button></div>
      </HudFrame>}
    </Materialise>
  </div>;
}
