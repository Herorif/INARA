import React, { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, AudioWaveform, BookOpen, Mic, Plus, Square } from 'lucide-react';
import useStore from '../store';
import HudLabel from '../shared/ui/HudLabel';
import PresenceRing from './PresenceRing';
import { liveVoice, voiceTarget } from '../features/voice';
import { emitSocket } from '../services/socket';
import { stageView } from './stageModel.js';
import { useVoiceStageReport } from './useVoiceStage.js';
import { replyNarration, replyStreaming } from '../store/replyStream.js';
import './conversation.css';

const starters = [
  { label: 'Plan my day', prompt: 'Help me plan my day.' },
  { label: 'Explore an idea', prompt: 'Help me turn an idea into a practical plan.' },
  { label: 'Check reminders', prompt: 'List my reminders.' },
];

/** "9:12:33 PM" or "21:12:33" becomes "21:12"; anything else is shown as given. */
export const shortTime = value => {
  const match = /(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp])?/.exec(value || '');
  if (!match) return value || '';
  let hour = Number(match[1]);
  if (match[3]) hour = (hour % 12) + (match[3].toLowerCase() === 'p' ? 12 : 0);
  return `${String(hour).padStart(2, '0')}:${match[2]}`;
};
const speaker = sender => sender === 'You' ? 'YOU' : sender === 'System' ? 'SYSTEM' : 'JARVIS';

/** Speaking core sizes (px): the header at rest (and the voice stage at narrow widths), the voice stage, the empty hero. */
const CORE_REST = 64, CORE_VOICE = 112, CORE_HERO = 150;
const NARROW = '(max-width: 680px)';

function useNarrow() {
  const [narrow, setNarrow] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(NARROW).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const query = window.matchMedia(NARROW);
    const change = () => setNarrow(query.matches);
    change();
    query.addEventListener('change', change);
    return () => query.removeEventListener('change', change);
  }, []);
  return narrow;
}

/** Stop talking: the renderer's own live voice, or the core's tray session. */
const stopVoice = target => {
  if (target === 'window') liveVoice().stop();
  else if (target === 'local') emitSocket('local_voice_stop', {});
};

export default function Conversation({ gaming = false, hidden = false }) {
  const messages = useStore(state => state.messages);
  const processing = useStore(state => state.textProcessing);
  const toolStep = useStore(state => state.textPhase === 'tool');
  const restoring = useStore(state => state.conversationRestoring);
  const connected = useStore(state => state.backendConnected);
  const input = useStore(state => state.inputValue);
  const project = useStore(state => state.currentProject);
  const conversationId = useStore(state => state.conversationId);
  const newChat = useStore(state => state.startNewConversation);
  const voice = useStore(state => state.voice);
  const local = useStore(state => state.localVoice);
  const localLevel = useStore(state => state.localVoiceLevel);
  const localEndedAt = useStore(state => state.localVoiceEndedAt);
  const narrow = useNarrow();
  const [, refresh] = useState(0);
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const composing = useRef(false);
  const followTail = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  const disabled = !connected || processing || restoring;
  const hands = voice.mode === 'conversation';
  const holdKey = event => event.type !== 'keydown' && event.type !== 'keyup' || ([' ', 'Enter'].includes(event.key) && !event.repeat);
  const projectLabel = project || 'temp';
  const state = !connected ? 'offline' : restoring ? 'restoring' : processing ? 'processing' : 'connected';
  // There is no stored session title; the first question names the session.
  const firstQuestion = messages.find(message => message.sender === 'You')?.text?.trim();
  const sessionTitle = firstQuestion ? firstQuestion.split('\n')[0] : 'New conversation';
  const stage = stageView({
    connected, processing, voice, caption: messages[messages.length - 1],
    local, localEndedAt, localLevel, now: Date.now(),
  });
  const speaking = stage.mode === 'voice';
  const empty = messages.length === 0;
  const coreSize = speaking && !narrow ? CORE_VOICE : CORE_REST;
  // The working line gives way to the reply as it streams, and returns while a tool step runs.
  const working = processing && (toolStep || !replyStreaming(messages));
  // What JARVIS said before the tool call it is running now.
  const narration = working ? replyNarration(messages) : null;
  useVoiceStageReport({ hidden });

  // A finished tray session's words are held for a moment; the stage rests when that ends.
  useEffect(() => {
    if (stage.until === null) return undefined;
    const timer = setTimeout(() => refresh(value => value + 1), Math.max(0, stage.until - Date.now()) + 20);
    return () => clearTimeout(timer);
  }, [stage.until]);

  useEffect(() => {
    followTail.current = true;
    setShowLatest(false);
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [conversationId]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    if (followTail.current) element.scrollTop = element.scrollHeight;
    else setShowLatest(true);
  }, [messages, processing, restoring]);

  useEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    let frame = 0;
    let measurement = '';
    const scheduleResize = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const style = getComputedStyle(element);
        const lineHeight = Number.parseFloat(style.lineHeight) || 24;
        const padding = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
        element.style.height = 'auto';
        element.style.height = `${Math.min(element.scrollHeight, lineHeight * 6 + padding)}px`;
      });
    };
    const observer = new ResizeObserver(() => {
      const style = getComputedStyle(element);
      const next = `${element.clientWidth}:${style.fontSize}:${style.lineHeight}`;
      // Height follows the text, so observing height as an input creates a loop.
      // Width and font changes are the only layout changes that require reflow.
      if (next === measurement) return;
      measurement = next;
      scheduleResize();
    });
    observer.observe(element.parentElement);
    window.addEventListener('resize', scheduleResize);
    document.fonts?.addEventListener('loadingdone', scheduleResize);
    scheduleResize();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', scheduleResize);
      document.fonts?.removeEventListener('loadingdone', scheduleResize);
    };
  }, [input]);

  const scrollToLatest = () => {
    followTail.current = true;
    setShowLatest(false);
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  };

  const suggest = text => {
    useStore.setState({ inputValue: text });
    inputRef.current?.focus();
  };

  const send = event => {
    event.preventDefault();
    if (composing.current || disabled || !input.trim()) return;
    followTail.current = true;
    setShowLatest(false);
    useStore.getState().handleSend({ key: 'Enter', isComposing: false });
  };

  return (
    <section className="conversation-panel conversation-workspace surface" aria-labelledby="conversation-title" data-conversation-state={state}>
      <header className="conversation-heading conversation-stage" data-stage={speaking ? 'voice' : empty ? 'empty' : 'rest'}>
        {(speaking || !empty) && <PresenceRing className="conversation-stage__core" size={coreSize} state={stage.presence} level={stage.level} lowPower={gaming} />}
        <div className="conversation-heading-copy">
          {speaking
            ? <HudLabel className={`conversation-stage__label${stage.stop ? ' is-live' : ''}`}>{`${stage.label} · ${stage.source}`}</HudLabel>
            : empty
              ? <HudLabel>CONVERSATION</HudLabel>
              : <HudLabel className="conversation-stage__label">CONVERSATION · <span className={`conversation-stage__state${stage.presence === 'working' ? ' is-live' : ''}`}>{stage.label}</span></HudLabel>}
          <h2 id="conversation-title" title={sessionTitle} hidden={speaking}>{sessionTitle}</h2>
          {speaking && <p className="conversation-stage__caption">{stage.caption && <span data-tone={stage.caption.tone}>{stage.caption.text}</span>}</p>}
        </div>
        {speaking
          ? stage.stop && <button className="conversation-stop btn btn--secondary btn--sm" type="button" onClick={() => stopVoice(stage.stop)}>
            <Square size={14} aria-hidden="true" /><span>Stop talking</span>
          </button>
          : <button className="conversation-new btn btn--ghost btn--sm" type="button" disabled={disabled} onClick={newChat} aria-label="New conversation">
            <Plus size={14} aria-hidden="true" /><span>New chat</span>
          </button>}
      </header>

      <div className="conversation-body">
        <div
          ref={scrollRef}
          className="conversation-scroll"
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          aria-label="Conversation"
          tabIndex={0}
          onScroll={() => {
            const element = scrollRef.current;
            followTail.current = element.scrollHeight - element.scrollTop - element.clientHeight < 64;
            if (followTail.current) setShowLatest(false);
          }}
        >
          <div className="conversation-column">
            {empty ? (!speaking &&
              <div className="chat-welcome conversation-welcome">
                <PresenceRing className="conversation-hero-core" size={CORE_HERO} state={stage.presence} lowPower={gaming} />
                <h3>Start a conversation</h3>
                <p>Say “Hey Jarvis”, hold the mic, or type below.</p>
                <div className="conversation-starters">
                  {starters.map(({ label, prompt }) => (
                    <button key={label} type="button" className="btn btn--secondary btn--sm" disabled={disabled} onClick={() => suggest(prompt)}>{label}</button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.length > 30 && <p className="conversation-history-note">Showing the latest 30 messages.</p>}
                {messages.slice(-30).map((message, index) => message.streaming && !message.text?.trim() ? null : (
                  // A streaming reply with no text yet (a tool step) shows only the working line.
                  <article key={`${conversationId}:${Math.max(messages.length - 30, 0) + index}`} className={`chat-message ${message.sender === 'You' ? 'from-you' : message.sender === 'System' ? 'from-system' : 'from-jarvis'}`} aria-busy={message.streaming || undefined}>
                    <div className="message-content">
                      <header className="message-meta hud-label">{speaker(message.sender)}{message.time && <> · <time>{shortTime(message.time)}</time></>}</header>
                      <p>{message.text}{message.streaming && <span className="reply-caret" aria-hidden="true" />}</p>
                      {message.stopped && <HudLabel className="message-stopped">STOPPED</HudLabel>}
                      {!!message.memory_sources?.length && (
                        <div className="memory-citations"><BookOpen size={12} aria-hidden="true" /><span>Project memory: {message.memory_sources.map(source => `${source.title} (v${source.version})`).join(' / ')}</span></div>
                      )}
                    </div>
                  </article>
                ))}
              </>
            )}
            {(working || restoring) && <div className="processing-line" role="status"><HudLabel>{restoring ? 'RESTORING CONVERSATION' : 'JARVIS · WORKING'}</HudLabel><span className="progress-line" aria-hidden="true" />{!restoring && narration && <p className="processing-narration" title={narration}>{narration}</p>}</div>}
          </div>
        </div>
        {showLatest && <button type="button" className="conversation-latest btn btn--secondary btn--sm" onClick={scrollToLatest}><ArrowDown size={14} aria-hidden="true" />Latest messages</button>}
      </div>

      <form className="composer" onSubmit={send}>
        <div className="composer-field">
          <textarea
            ref={inputRef}
            rows={1}
            aria-label="Message JARVIS"
            aria-describedby="conversation-input-help"
            placeholder={restoring ? 'Restoring your conversation…' : !connected ? 'Connect the core to start a conversation' : 'Ask JARVIS anything'}
            value={input}
            onChange={event => useStore.setState({ inputValue: event.target.value })}
            disabled={disabled}
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={() => { composing.current = false; }}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && event.nativeEvent.keyCode !== 229) send(event);
            }}
          />
          <div className="conversation-compose-actions">
            <button type="button" className={`conversation-voice btn btn--ghost btn--icon ${hands ? 'is-on' : ''}`} aria-pressed={hands} disabled={disabled} aria-label="Conversation mode" title="Conversation: talk hands-free" onClick={() => liveVoice().toggleConversation(voiceTarget())}><AudioWaveform size={16} aria-hidden="true" /></button>
            <button type="button" className={`conversation-talk btn btn--ghost btn--icon ${voice.micOpen && !hands ? 'holding' : ''}`} disabled={disabled || hands} aria-label="Hold to talk" title="Hold to talk"
              onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); event.preventDefault(); liveVoice().holdStart(voiceTarget()); }}
              onPointerUp={event => { event.preventDefault(); liveVoice().holdEnd(); }}
              onPointerCancel={() => liveVoice().holdEnd()}
              onKeyDown={event => { if (!holdKey(event)) return; event.preventDefault(); liveVoice().holdStart(voiceTarget()); }}
              onKeyUp={event => { if (!holdKey(event)) return; event.preventDefault(); liveVoice().holdEnd(); }}><Mic size={16} aria-hidden="true" /></button>
            <button className="send-button btn btn--primary btn--icon" type="submit" aria-label="Send" disabled={disabled || !input.trim()}><ArrowUp size={16} aria-hidden="true" /></button>
          </div>
        </div>
        <div className="composer-foot" id="conversation-input-help">
          <HudLabel>{`PROJECT · ${projectLabel}`}</HudLabel>
          {stage.microphone ? <HudLabel className="composer-foot__mic">{`MICROPHONE ON · ${stage.source}`}</HudLabel> : <HudLabel className="composer-foot__keys">ENTER TO SEND · SHIFT+ENTER FOR NEW LINE · HOLD MIC TO TALK</HudLabel>}
        </div>
      </form>
    </section>
  );
}
