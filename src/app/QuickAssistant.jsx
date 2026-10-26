import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, Mic, Square, Maximize2, Keyboard, X } from 'lucide-react';
import useStore from '../store';
import socket from '../services/socket';
import { SpeechController } from '../features/speech/controller';
import PresenceRing from './PresenceRing';
import HudLabel from '../shared/ui/HudLabel';
import './quick-assistant.css';
const labels = {
  idle: 'Ready when you are',
  armed: 'Hold to talk when ready',
  opening: 'Preparing push-to-talk',
  listening: 'Listening while held',
  transcribing: 'Transcribing your voice',
  review: 'Review before sending',
  thinking: 'Thinking',
  speaking: 'Speaking locally',
  answered: 'Answer ready'
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
    deviceId = useStore(s => s.selectedMicId);
  const [voice, setVoice] = useState({
      state: 'idle',
      transcript: '',
      error: ''
    }),
    [text, setText] = useState(''),
    [speak, setSpeak] = useState(false);
  const controller = useRef(null),
    input = useRef(null);
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
          useStore.getState().addMessage('INARA', answer, sources);
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
  }, [project, conversationId, deviceId]);
  useEffect(() => {
    if (gaming || locked) controller.current?.cancel(gaming ? 'Voice pauses in gaming mode. Typed input is available.' : 'Workspace locked.');
  }, [gaming, locked]);
  const active = !['idle', 'answered'].includes(voice.state);
  const presence = !connected ? 'offline' : ['opening', 'listening'].includes(voice.state) ? 'listening' : voice.state === 'speaking' ? 'speaking' : processing || ['transcribing', 'thinking'].includes(voice.state) ? 'working' : 'idle';
  const send = event => {
    event.preventDefault();
    if (!connected || locked || processing || restoring || (active && voice.state !== 'review')) return;
    if (voice.state === 'review') {
      controller.current.send(voice.transcript, speak);
      return;
    }
    if (useStore.getState().sendText(text)) setText('');
  };
  const hold = event => {
    if (event.type === 'keydown' && (event.repeat || ![' ', 'Enter'].includes(event.key))) return;
    event.preventDefault();
    controller.current.record(deviceId);
  };
  const release = event => {
    if (event.type === 'keyup' && ![' ', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    controller.current.release();
  };
  return <section className="quick-assistant" aria-labelledby="quick-title" data-speech-state={voice.state}>
    <header className="quick-header"><div className="quick-header__brand"><span className="monogram" aria-hidden="true">I</span><HudLabel>QUICK ASSISTANT</HudLabel></div><div className="quick-header__actions"><button type="button" className="btn btn--ghost btn--icon" aria-label="Open full workspace" title="Open full workspace" onClick={onExpand}><Maximize2 size={16} aria-hidden="true" /></button><button type="button" className="btn btn--ghost btn--icon" aria-label="Close quick assistant" onClick={onClose}><X size={16} aria-hidden="true" /></button></div></header>
    <div className="quick-signal"><PresenceRing size={64} state={presence} /></div>
    <span className="eyebrow quick-status">{project} · {connected ? 'CORE CONNECTED' : 'CORE OFFLINE'}</span><h1 id="quick-title">{processing ? 'Thinking' : labels[voice.state]}</h1>
    <p className="quick-subtitle">Type anytime. Hold to speak. Your transcript waits for review.</p>
    <div className="quick-log" aria-label="Recent conversation" aria-live="polite">{messages.filter(message => ['You', 'INARA'].includes(message.sender)).slice(-6).map((message, index) => <article key={index} className={message.sender === 'INARA' ? 'assistant' : 'user'}><small className="hud-label">{message.sender === 'INARA' ? 'INARA' : 'YOU'}</small><p>{message.text}</p>{!!message.memory_sources?.length && <small>Project memory: {message.memory_sources.map(source => source.title).join(" / ")}</small>}</article>)}</div>
    {voice.error && <p className="quick-error" role="alert">{voice.error}</p>}
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
    <div className="quick-voice">{['idle', 'answered'].includes(voice.state) && <button type="button" className="prepare-voice btn btn--secondary" disabled={!connected || gaming || locked || processing || restoring} onClick={() => controller.current.begin({
        project,
        conversationId,
        deviceId
      })}>Prepare voice</button>}<button type="button" className={`ptt-button btn btn--secondary ${voice.state === 'listening' ? 'holding' : ''}`} disabled={!connected || gaming || locked || processing || restoring || !['armed', 'opening', 'listening'].includes(voice.state)} onPointerDown={event => {
        event.currentTarget.setPointerCapture(event.pointerId);
        hold(event);
      }} onPointerUp={release} onPointerCancel={() => controller.current.cancel()} onKeyDown={hold} onKeyUp={release}><Mic size={16} aria-hidden="true" />Hold to talk</button><button type="button" className="btn btn--ghost" disabled={!active && !processing} onClick={() => {
        controller.current.cancel();
        if (processing) socket.emit('cancel_conversation', {});
      }}><Square size={14} aria-hidden="true" />Interrupt</button></div>
    <label className="quick-speak"><input type="checkbox" checked={speak} onChange={event => setSpeak(event.target.checked)} />Speak voice answers with an available local voice</label>
    <footer className="hud-label">MICROPHONE OFF WHEN RELEASED · NO WAKE LISTENING</footer>
  </section>;
}
