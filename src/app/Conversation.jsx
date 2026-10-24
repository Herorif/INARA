import React, { useEffect, useRef, useState } from 'react';
import {
  ArrowDown, ArrowUp, ArrowUpRight, AudioLines, Bell, BookOpen,
  CalendarDays, Folder, Lightbulb, Plus, Sparkles, User,
} from 'lucide-react';
import useStore from '../store';
import './conversation.css';

const starters = [
  { icon: CalendarDays, label: 'Make a plan', prompt: 'Help me plan my day.' },
  { icon: Lightbulb, label: 'Explore an idea', prompt: 'Help me turn an idea into a practical plan.' },
  { icon: Bell, label: 'Check reminders', prompt: 'List my reminders.' },
];

export default function Conversation({ onOpen, onQuick } = {}) {
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
  const projectLabel = !project || project === 'temp' ? 'Personal workspace' : project;
  const state = !connected ? 'offline' : restoring ? 'restoring' : processing ? 'processing' : 'connected';
  const status = {
    offline: 'Core offline',
    restoring: 'Restoring conversation',
    processing: 'Working on your request',
    connected: 'Core connected',
  }[state];

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
          <div className="conversation-channel"><span className={`status-dot ${!connected ? 'offline' : ''}`} /><span>{status}</span></div>
          <h2 id="conversation-title">Your assistant<span className="heading-dot">.</span></h2>
        </div>
        <button className="conversation-new" type="button" disabled={disabled} onClick={newChat} aria-label="New conversation">
          <Plus size={16} aria-hidden="true" /><span>New chat</span>
        </button>
      </header>

      <div className="conversation-project">
        <span><Folder size={13} aria-hidden="true" /><span>{projectLabel}</span></span>
        {onOpen && <button type="button" onClick={() => onOpen('memory')}><BookOpen size={13} aria-hidden="true" />Project memory<ArrowUpRight size={12} aria-hidden="true" /></button>}
      </div>

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
          {messages.length === 0 ? (
            <div className="chat-welcome conversation-welcome">
              <div className="conversation-emblem" aria-hidden="true"><Sparkles size={29} strokeWidth={1.25} /></div>
              <span className="conversation-kicker">A LITTLE INTELLIGENCE. MORE POSSIBILITY.</span>
              <h3>Where shall we begin?</h3>
              <p>Ask a question, work through a plan,<br className="conversation-welcome-break" /> or give your next idea a place to start.</p>
              <div className="conversation-starters">
                {starters.map(({ icon: Icon, label, prompt }) => (
                  <button key={label} type="button" disabled={disabled} onClick={() => suggest(prompt)}>
                    <Icon size={17} strokeWidth={1.6} aria-hidden="true" /><span>{label}</span><ArrowUpRight size={13} aria-hidden="true" />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.length > 30 && <p className="conversation-history-note">Showing the latest 30 messages.</p>}
              {messages.slice(-30).map((message, index) => (
                <article key={`${conversationId}:${Math.max(messages.length - 30, 0) + index}`} className={`chat-message ${message.sender === 'You' ? 'from-you' : ''} ${message.sender === 'System' ? 'from-system' : ''}`}>
                  <span className="message-avatar" aria-hidden="true">{message.sender === 'You' ? <User size={15} /> : message.sender === 'System' ? '·' : <Sparkles size={15} />}</span>
                  <div className="message-content">
                    <header><strong>{message.sender}</strong>{message.time && <time>{message.time}</time>}</header>
                    <p>{message.text}</p>
                    {!!message.memory_sources?.length && (
                      <div className="memory-citations"><BookOpen size={12} aria-hidden="true" /><span>Project memory: {message.memory_sources.map(source => `${source.title} (v${source.version})`).join(' / ')}</span></div>
                    )}
                  </div>
                </article>
              ))}
            </>
          )}
          {(processing || restoring) && <div className="processing-line" role="status"><span /><span /><span />{restoring ? 'Restoring your conversation' : 'INARA is thinking'}</div>}
        </div>
        {showLatest && <button type="button" className="conversation-latest" onClick={scrollToLatest}><ArrowDown size={14} aria-hidden="true" />Latest messages</button>}
      </div>

      <form className="composer" onSubmit={send}>
        <div className="composer-field">
          <textarea
            ref={inputRef}
            rows={1}
            aria-label="Message INARA"
            aria-describedby="conversation-input-help"
            placeholder={restoring ? 'Restoring your conversation…' : !connected ? 'Connect the core to start a conversation…' : 'Ask, imagine, create…'}
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
            {onQuick && <button type="button" className="conversation-quick" onClick={onQuick} disabled={disabled} aria-label="Open quick assistant" title="Open quick assistant"><AudioLines size={18} aria-hidden="true" /></button>}
            <button className="send-button" type="submit" aria-label="Send message" disabled={disabled || !input.trim()}><ArrowUp size={19} aria-hidden="true" /></button>
          </div>
        </div>
        <div className="composer-foot" id="conversation-input-help">
          <span>{!connected ? 'Waiting for the core connection' : restoring ? 'Your saved conversation is loading' : processing ? 'Your request is in progress' : 'Your project. Your direction.'}</span>
          <span><kbd>Enter</kbd> send <span aria-hidden="true">·</span> <kbd>Shift Enter</kbd> new line</span>
        </div>
      </form>
    </section>
  );
}
