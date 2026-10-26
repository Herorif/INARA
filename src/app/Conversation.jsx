import React, { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, BookOpen, Mic, Plus } from 'lucide-react';
import useStore from '../store';
import HudLabel from '../shared/ui/HudLabel';
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
const speaker = sender => sender === 'You' ? 'YOU' : sender === 'System' ? 'SYSTEM' : 'INARA';

export default function Conversation({ onQuick } = {}) {
  const messages = useStore(state => state.messages);
  const processing = useStore(state => state.textProcessing);
  const restoring = useStore(state => state.conversationRestoring);
  const connected = useStore(state => state.backendConnected);
  const input = useStore(state => state.inputValue);
  const project = useStore(state => state.currentProject);
  const conversationId = useStore(state => state.conversationId);
  const newChat = useStore(state => state.startNewConversation);
  const inputRef = useRef(null);
  const scrollRef = useRef(null);
  const composing = useRef(false);
  const followTail = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  const disabled = !connected || processing || restoring;
  const projectLabel = project || 'temp';
  const state = !connected ? 'offline' : restoring ? 'restoring' : processing ? 'processing' : 'connected';
  // There is no stored session title; the first question names the session.
  const firstQuestion = messages.find(message => message.sender === 'You')?.text?.trim();
  const sessionTitle = firstQuestion ? firstQuestion.split('\n')[0] : 'New conversation';

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
      <header className="conversation-heading">
        <div className="conversation-heading-copy">
          <HudLabel>CONVERSATION</HudLabel>
          <h2 id="conversation-title" title={sessionTitle}>{sessionTitle}</h2>
        </div>
        <button className="conversation-new btn btn--ghost btn--sm" type="button" disabled={disabled} onClick={newChat} aria-label="New conversation">
          <Plus size={14} aria-hidden="true" /><span>New chat</span>
        </button>
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
            {messages.length === 0 ? (
              <div className="chat-welcome conversation-welcome">
                <span className="monogram monogram--md" aria-hidden="true">I</span>
                <h3>Start a conversation</h3>
                <p>Ask a question, plan your day, or hand over a task.</p>
                <div className="conversation-starters">
                  {starters.map(({ label, prompt }) => (
                    <button key={label} type="button" className="btn btn--secondary btn--sm" disabled={disabled} onClick={() => suggest(prompt)}>{label}</button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.length > 30 && <p className="conversation-history-note">Showing the latest 30 messages.</p>}
                {messages.slice(-30).map((message, index) => (
                  <article key={`${conversationId}:${Math.max(messages.length - 30, 0) + index}`} className={`chat-message ${message.sender === 'You' ? 'from-you' : message.sender === 'System' ? 'from-system' : 'from-inara'}`}>
                    <div className="message-content">
                      <header className="message-meta hud-label">{speaker(message.sender)}{message.time && <> · <time>{shortTime(message.time)}</time></>}</header>
                      <p>{message.text}</p>
                      {!!message.memory_sources?.length && (
                        <div className="memory-citations"><BookOpen size={12} aria-hidden="true" /><span>Project memory: {message.memory_sources.map(source => `${source.title} (v${source.version})`).join(' / ')}</span></div>
                      )}
                    </div>
                  </article>
                ))}
              </>
            )}
            {(processing || restoring) && <div className="processing-line" role="status"><HudLabel>{restoring ? 'RESTORING CONVERSATION' : 'INARA · WORKING'}</HudLabel><span className="progress-line" aria-hidden="true" /></div>}
          </div>
        </div>
        {showLatest && <button type="button" className="conversation-latest btn btn--secondary btn--sm" onClick={scrollToLatest}><ArrowDown size={14} aria-hidden="true" />Latest messages</button>}
      </div>

      <form className="composer" onSubmit={send}>
        <div className="composer-field">
          <textarea
            ref={inputRef}
            rows={1}
            aria-label="Message INARA"
            aria-describedby="conversation-input-help"
            placeholder={restoring ? 'Restoring your conversation…' : !connected ? 'Connect the core to start a conversation' : 'Ask INARA anything'}
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
            {onQuick && <button type="button" className="conversation-quick btn btn--ghost btn--icon" onClick={onQuick} disabled={disabled} aria-label="Open quick assistant" title="Open quick assistant"><Mic size={16} aria-hidden="true" /></button>}
            <button className="send-button btn btn--primary btn--icon" type="submit" aria-label="Send" disabled={disabled || !input.trim()}><ArrowUp size={16} aria-hidden="true" /></button>
          </div>
        </div>
        <div className="composer-foot" id="conversation-input-help">
          <HudLabel>{`PROJECT · ${projectLabel}`}</HudLabel>
          <HudLabel className="composer-foot__keys">ENTER TO SEND · SHIFT+ENTER FOR NEW LINE</HudLabel>
        </div>
      </form>
    </section>
  );
}
