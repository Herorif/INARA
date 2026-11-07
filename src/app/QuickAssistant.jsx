import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, AudioWaveform, Mic, Square, Maximize2, Keyboard, X } from 'lucide-react';
import useStore from '../store';
import socket from '../services/socket';
import { SpeechController } from '../features/speech/controller';
import { liveVoice, voiceTarget } from '../features/voice';
import { microphoneDeviceId } from '../features/voice/microphone.js';
import { holdButtonTone, shouldStartConversation } from '../features/voice/defaultMode.js';
import PresenceRing from './PresenceRing';
import HudLabel from '../shared/ui/HudLabel';
import BrandMark from '../shared/ui/BrandMark';
import './quick-assistant.css';
const labels = {
  idle: 'Ready when you are',
  armed: 'Hold to dictate when ready',
  opening: 'Preparing push-to-talk',
  listening: 'Listening while held',
  transcribing: 'Transcribing your voice',
  review: 'Review before sending',
  thinking: 'Thinking',
  speaking: 'Speaking locally',
  answered: 'Answer ready'
};
const liveLabels = {
  connecting: 'Connecting voice',
  idle: 'Ready when you are',
  listening: 'Listening',
  thinking: 'Thinking',
  working: 'Working on it',
  speaking: 'Speaking'
};
export default function QuickAssistant({
  onExpand,
  onClose,
  gaming
}) {
  const project = useStore(s => s.currentProject),
    conversationId = useStore(s => s.conversationId),
    connected = useStore(s => s.backendConnected),
    locked = useStore(s => s.isLockScreenVisible),
    processing = useStore(s => s.textProcessing),
    restoring = useStore(s => s.conversationRestoring),
    messages = useStore(s => s.messages),
    live = useStore(s => s.voice),
    defaultMode = useStore(s => s.voiceDefaultMode),
    openedAt = useStore(s => s.quickOpenedAt);
  const [voice, setVoice] = useState({
      state: 'idle',
      transcript: '',
      error: ''
    }),
    [text, setText] = useState(''),
    [speak, setSpeak] = useState(false);
  const controller = useRef(null),
    input = useRef(null),
    startedFor = useRef(null);
  useEffect(() => {
    let live = true;
    const value = new SpeechController({
      socket,
      onChange: patch => {
        if (patch.cancelledTurnId) {
          const store = useStore.getState();
          store.confirmationQueue.filter(request => request.speech_turn_id === patch.cancelledTurnId).forEach(request => store.resolveConfirmation(request.id));
        }
        if (live) setVoice(previous => ({
          ...previous,
          ...patch
        }));
      },
      onAnswer: (question, answer, sources) => {
        if (live) {
          useStore.getState().addMessage('You', question);
          useStore.getState().addMessage('JARVIS', answer, sources);
        }
      }
    });
    controller.current = value;
    const pause = () => { if (!['idle', 'answered'].includes(value.state)) value.cancel('Capture paused. Prepare a new turn when ready.'); };
    const visibility = () => {
      if (document.hidden) pause();
    };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('blur', pause);
    const off = window.electronAPI?.onCapturePause(pause);
    input.current?.focus();
    return () => {
      live = false;
      value.dispose();
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('blur', pause);
      off?.();
    };
  }, [project, conversationId]);
  useEffect(() => {
    if (gaming || locked) {
      controller.current?.cancel(gaming ? 'Voice pauses in gaming mode. Typed input is available.' : 'Workspace locked.');
      if (liveVoice().active()) liveVoice().stop();
    }
  }, [gaming, locked]);
  // Default mode Conversation: opening the Quick assistant (the hotkey) turns it on once.
  useEffect(() => {
    if (openedAt == null || !shouldStartConversation({ mode: defaultMode, started: startedFor.current === openedAt, elapsed: performance.now() - openedAt, connected, gaming, locked, restoring, liveState: live.state, speechState: voice.state })) return;
    startedFor.current = openedAt;
    liveVoice().toggleConversation(voiceTarget());
  }, [openedAt, defaultMode, connected, gaming, locked, restoring, live.state, voice.state]);
  const active = !['idle', 'answered'].includes(voice.state);
  const dictating = ['armed', 'opening', 'listening'].includes(voice.state);
  const talking = live.state !== 'off';
  const hands = live.mode === 'conversation';
  const presence = !connected ? 'offline' : ['opening', 'listening'].includes(voice.state) || live.state === 'listening' ? 'listening' : voice.state === 'speaking' || live.state === 'speaking' ? 'speaking' : processing || ['transcribing', 'thinking'].includes(voice.state) || ['connecting', 'thinking', 'working'].includes(live.state) ? 'working' : 'idle';
  const title = processing ? 'Thinking' : active ? labels[voice.state] : talking ? liveLabels[live.state] || labels.idle : labels[voice.state];
  const send = event => {
    event.preventDefault();
    if (!connected || locked || processing || restoring || (active && voice.state !== 'review')) return;
    if (voice.state === 'review') {
      controller.current.send(voice.transcript, speak);
      return;
    }
    if (useStore.getState().sendText(text)) setText('');
  };
  // Hold to talk runs a live voice turn; after Dictate it records a transcript to review.
  const hold = event => {
    if (event.type === 'keydown' && (event.repeat || ![' ', 'Enter'].includes(event.key))) return;
    event.preventDefault();
    if (dictating) controller.current.record(microphoneDeviceId);
    else liveVoice().holdStart(voiceTarget());
  };
  const release = event => {
    if (event.type === 'keyup' && ![' ', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    if (dictating) controller.current.release();
    else liveVoice().holdEnd();
  };
  const cancelHold = () => {
    if (dictating) controller.current.cancel();
    else liveVoice().holdEnd();
  };
  return <section className="quick-assistant" aria-labelledby="quick-title" data-speech-state={voice.state} data-voice-state={live.state} data-voice-mode={live.mode || 'none'} data-microphone={live.micOpen ? 'on' : 'off'}>
    <header className="quick-header"><div className="quick-header__brand"><BrandMark size={24} /><HudLabel>QUICK ASSISTANT</HudLabel></div><div className="quick-header__actions"><button type="button" className="btn btn--ghost btn--icon" aria-label="Open full workspace" title="Open full workspace" onClick={onExpand}><Maximize2 size={16} aria-hidden="true" /></button><button type="button" className="btn btn--ghost btn--icon" aria-label="Close quick assistant" onClick={onClose}><X size={16} aria-hidden="true" /></button></div></header>
    <div className="quick-signal"><PresenceRing size={64} state={presence} level={live.level} lowPower={gaming} /></div>
    <span className="eyebrow quick-status">{project} · {connected ? 'CORE CONNECTED' : 'CORE OFFLINE'}</span><h1 id="quick-title">{title}</h1>
    <p className="quick-subtitle">Type anytime. Hold to talk, or turn on Conversation to talk hands-free. Dictate to review before sending.</p>
    <div className="quick-log" aria-label="Recent conversation" aria-live="polite">{messages.filter(message => ['You', 'JARVIS'].includes(message.sender)).slice(-6).map((message, index) => <article key={index} className={message.sender === 'JARVIS' ? 'assistant' : 'user'}><small className="hud-label">{message.sender === 'JARVIS' ? 'JARVIS' : 'YOU'}</small><p>{message.text}</p>{!!message.memory_sources?.length && <small>Project memory: {message.memory_sources.map(source => source.title).join(" / ")}</small>}</article>)}</div>
    {voice.error && <p className="quick-error" role="alert">{voice.error}</p>}
    {live.error && <p className="quick-error quick-error--voice" role="alert">{live.error}</p>}
    {gaming && <p className="quick-note">Gaming mode: microphone capture is paused.</p>}
    <form onSubmit={send}><label htmlFor="quick-input"><Keyboard size={14} aria-hidden="true" />{voice.state === 'review' ? 'Review and edit the transcript' : 'Your message'}</label><div className="quick-composer"><textarea ref={input} id="quick-input" maxLength={12000} value={voice.state === 'review' ? voice.transcript : text} disabled={processing || ['opening', 'listening', 'transcribing', 'thinking'].includes(voice.state) || locked} placeholder="What can I help with?" onChange={event => voice.state === 'review' ? setVoice(previous => ({
          ...previous,
          transcript: event.target.value
        })) : setText(event.target.value)} onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            send(event);
          }
        }} /><button type="submit" className="btn btn--primary btn--icon" aria-label="Send quick message" disabled={!connected || locked || processing || restoring || active && voice.state !== 'review' || !(voice.state === 'review' ? voice.transcript : text).trim()}><ArrowUp size={16} aria-hidden="true" /></button></div></form>
    <div className="quick-voice"><button type="button" className={`ptt-button btn ${holdButtonTone(defaultMode)} ${voice.state === 'listening' || (live.micOpen && !hands) ? 'holding' : ''}`} disabled={!connected || gaming || locked || processing || restoring || hands || (active && !dictating)} onPointerDown={event => {
        event.currentTarget.setPointerCapture(event.pointerId);
        hold(event);
      }} onPointerUp={release} onPointerCancel={cancelHold} onKeyDown={hold} onKeyUp={release}><Mic size={16} aria-hidden="true" />{dictating ? 'Hold to dictate' : 'Hold to talk'}</button><button type="button" className={`conversation-toggle btn btn--secondary ${hands ? 'is-on' : ''}`} aria-pressed={hands} disabled={!connected || gaming || locked || restoring || active} onClick={() => liveVoice().toggleConversation(voiceTarget())}><AudioWaveform size={16} aria-hidden="true" />Conversation</button>{['idle', 'answered'].includes(voice.state) && <button type="button" className="dictate-voice btn btn--ghost" disabled={!connected || gaming || locked || processing || restoring || hands || live.micOpen} onClick={async () => {
        if (liveVoice().active()) await liveVoice().stop();
        controller.current.begin({
          project,
          conversationId
        });
      }}>Dictate</button>}<button type="button" className="interrupt-voice btn btn--ghost" disabled={!active && !processing && !talking} onClick={() => {
        controller.current.cancel();
        if (liveVoice().active()) liveVoice().stop();
        if (processing) socket.emit('cancel_conversation', {});
      }}><Square size={14} aria-hidden="true" />Stop speaking</button></div>
    <label className="quick-speak"><input type="checkbox" checked={speak} onChange={event => setSpeak(event.target.checked)} />Read dictated answers aloud with a local voice</label>
    <footer className="hud-label">{live.micOpen || voice.state === 'listening' ? `MICROPHONE ON${hands ? ' · CONVERSATION' : ''}` : 'MICROPHONE OFF'} · NO WAKE LISTENING</footer>
  </section>;
}
