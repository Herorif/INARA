import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, ArrowUpRight, Gauge, BookOpen, Smartphone, AudioLines, Bell, Box, Camera, ChevronRight, Cpu, Gamepad2, Globe2, LayoutDashboard, Layers3, Maximize2, Minus, Power, Settings2, ShieldCheck, Sparkles, X, Zap, Search, History } from 'lucide-react';
import useStore from '../store';
import socket, { emitSocket } from '../services/socket';
import CoreOrb from './CoreOrb';
import FeatureDialog from './FeatureDialog';
import ReminderAlert from '../components/ReminderAlert';
import ConfirmationPopup from '../components/ConfirmationPopup';
import './workspace.css';
import { UI_CONTRACT_VERSION } from '../transport/generated/version.ts';
import { flags, heavyFeatures } from './features';
const CommandPalette = lazy(() => import('./CommandPalette'));
const QuickAssistant = lazy(() => import('./QuickAssistant'));
const ActivityCenter = lazy(() => import('./ActivityCenter'));
import PanelState from './PanelState';
const AuthLock = lazy(() => import('../components/AuthLock'));
function Clock() {
  const [time, setTime] = useState(new Date());
  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 60000);
    return () => clearInterval(timer);
  }, []);
  return <div className="deck-clock"><strong>{time.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit'
      })}</strong>
        <span>{time.toLocaleDateString([], {
        weekday: 'short',
        day: '2-digit',
        month: 'short'
      })}</span></div>;
}
function Conversation() {
  const messages = useStore(s => s.messages);
  const processing = useStore(s => s.textProcessing);
  const restoring = useStore(s => s.conversationRestoring);
  const connected = useStore(s => s.backendConnected);
  const input = useStore(s => s.inputValue);
  const newChat = useStore(s => s.startNewConversation);
  const inputRef = useRef(null),
    end = useRef(null);
  useEffect(() => {
    end.current?.scrollIntoView({
      block: 'nearest'
    });
  }, [messages, processing]);
  const suggest = text => {
    useStore.setState({
      inputValue: text
    });
    inputRef.current?.focus();
  };
  return <section className="conversation-panel surface" aria-labelledby="conversation-title">
        <div className="section-heading"><div><span className="eyebrow">DIRECT CHANNEL</span><h2 id="conversation-title">You & INARA<span className="heading-dot">.</span></h2></div>
            <button className="text-button" disabled={!connected || processing || restoring} onClick={newChat}>New conversation <span>+</span></button></div>
        <div className="conversation-scroll" role="log" aria-live="polite" aria-label="Conversation">
            {messages.length === 0 ? <div className="chat-welcome"><div className="welcome-mark"><Sparkles size={24} /></div>
                <h3>What’s on your mind?</h3><p>A quick question, an ambitious idea, or something you’d rather hand over.</p>
                <div className="suggestions">{['Help me plan my day', 'What can we build together?', 'List my reminders'].map(text => <button key={text} onClick={() => suggest(text)}>{text}<ArrowUpRight size={14} /></button>)}</div>
            </div> : messages.slice(-30).map((message, index) => <article key={index} className={`chat-message ${message.sender === 'You' ? 'from-you' : ''}`}>
                <span className="message-avatar">{message.sender === 'You' ? 'H' : message.sender === 'System' ? '·' : 'I'}</span>
                <div><header><strong>{message.sender}</strong>{message.time && <time>{message.time}</time>}</header><p>{message.text}</p>{!!message.memory_sources?.length && <small className="memory-citations">Project memory: {message.memory_sources.map(source => `${source.title} (v${source.version})`).join(" / ")}</small>}</div></article>)}
            {processing && <div className="processing-line"><span /><span /><span /> INARA is thinking</div>}<div ref={end} />
        </div>
        <form className="composer" onSubmit={event => {
      event.preventDefault();
      useStore.getState().handleSend({
        key: 'Enter',
        isComposing: false
      });
    }}>
            <div className="composer-field"><Sparkles size={18} /><input ref={inputRef} aria-label="Message INARA" placeholder={restoring ? 'Restoring your conversation…' : 'Ask, imagine, create…'} value={input} onChange={event => useStore.setState({
          inputValue: event.target.value
        })} disabled={!connected || processing || restoring} />
                <button className="send-button" type="submit" aria-label="Send message" disabled={!connected || processing || restoring || !input.trim()}><ArrowUp size={19} /></button></div>
            <div className="composer-foot"><span><ShieldCheck size={12} /> Your project. Your permission.</span><span>{connected ? 'ENTER TO SEND' : 'WAITING FOR BACKEND'}</span></div>
        </form>
    </section>;
}
function FeatureCard({
  icon: Icon,
  title,
  description,
  tag,
  onClick,
  disabled
}) {
  return <button className="feature-card" onClick={onClick} disabled={disabled}><span className="feature-icon"><Icon size={24} /></span>
        <span className="feature-tag">{tag}</span><strong>{title}</strong><p>{description}</p><span className="feature-arrow"><ArrowUpRight size={20} /></span></button>;
}
export default function CommandDeck() {
  const quick = useStore(s => s.showQuickAssistant);
  const setQuick = useCallback(value => { if (value) { setCamera(false); setCommands(false); useStore.setState(Object.fromEntries(Object.values(flags).map(flag => [flag, false]))); } useStore.setState({showQuickAssistant:value}); window.electronAPI?.setQuickMode?.(value); }, []);
  useEffect(() => window.electronAPI?.onQuickAssistant?.(setQuick), [setQuick]);
  const [commands, setCommands] = useState(false);
  const closeCommands = useCallback(() => setCommands(false), []);
  const [page, setPage] = useState('assistant'),
    [camera, setCamera] = useState(false);
  const [resident, setResident] = useState({
      phase: 'browser',
      visible: true,
      gaming: false
    }),
    [memory, setMemory] = useState(null);
  const connected = useStore(s => s.backendConnected),
    processing = useStore(s => s.textProcessing);
  const currentProject = useStore(s => s.currentProject),
    aiConnected = useStore(s => s.aiConnected);
  const reminders = useStore(s => s.reminders),
    locked = useStore(s => s.isLockScreenVisible);
  const activeFlag = useStore(s => Object.keys(flags).find(key => s[flags[key]]) || null);
  const [resource, setResource] = useState({
    state: 'chat'
  });
  const gaming = resident.gaming || resource.state === 'gaming';
  const activeFeature = camera ? 'camera' : activeFlag;
  const closeFeature = useCallback(() => {
    setCamera(false);
    useStore.setState(Object.fromEntries(Object.values(flags).map(flag => [flag, false])));
  }, []);
  useEffect(() => {
    const api = window.electronAPI;
    api?.residentStatus().then(value => {
      if (value) setResident(value);
    });
    const cleanup = api?.onResidentState(setResident);
    const resourceUpdate = value => setResource(value);
    socket.on('resource_state', resourceUpdate);
    const metrics = async () => {
      const value = await api?.metrics();
      if (value) setMemory(value.electronMemoryMB);
    };
    metrics();
    const interval = setInterval(metrics, 10000);
    return () => {
      cleanup?.();
      clearInterval(interval);
      socket.off('resource_state', resourceUpdate);
    };
  }, []);
  useEffect(() => {
    if (gaming) closeFeature();
  }, [gaming, closeFeature]);
  const openFeature = (feature, heavy = heavyFeatures.has(feature), requestId = null) => {
    if (feature === 'quick') { if (!locked) setQuick(true); return; }
    if (locked || (gaming && heavy)) return;
    useStore.setState({ studioSelection: requestId ? { feature, requestId, project: currentProject } : null });
    closeFeature();
    if (heavy) emitSocket('set_resource_state', {
      state: 'studio'
    });
    if (feature === 'camera') setCamera(true);else useStore.setState({
      [flags[feature]]: true
    });
    if (feature === 'reminder') emitSocket('get_reminders');
    if (feature === 'settings' && navigator.mediaDevices) navigator.mediaDevices.enumerateDevices().then(devices => useStore.setState({
      micDevices: devices.filter(d => d.kind === 'audioinput'),
      speakerDevices: devices.filter(d => d.kind === 'audiooutput'),
      webcamDevices: devices.filter(d => d.kind === 'videoinput')
    })).catch(() => {});
  };
  const toggleGaming = async () => {
    const value = !gaming;
    try {
      await window.electronAPI?.setGaming(value);
    } catch {
      setResident(previous => ({ ...previous, error: 'Gaming mode could not change. Check the core connection and retry.' }));
      return;
    }
    setResident(previous => ({
      ...previous,
      gaming: value
    }));
    emitSocket('set_resource_state', {
      state: value ? 'gaming' : 'chat'
    });
  };
  useEffect(() => {
    const key = event => {
      if (event.ctrlKey && event.shiftKey && event.code === 'Space') { event.preventDefault(); setQuick(true); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !activeFeature && !locked) {
        event.preventDefault(); setCommands(value => !value);
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [activeFeature, locked]);
  useEffect(() => { if (locked) setCommands(false); }, [locked]);
  const pending = reminders.filter(r => r.status === 'pending' || r.status === 'snoozed');
  return <div className={`command-deck ${gaming ? 'gaming-mode' : ''} ${quick ? 'quick-mode' : ''}`} data-resource-state={resource.state} data-ui-contract-version={UI_CONTRACT_VERSION}>
        {quick && <Suspense fallback={<PanelState kind="loading" title="Preparing quick assistant" />}><QuickAssistant gaming={gaming} onExpand={() => setQuick(false)} onClose={() => window.electronAPI ? window.electronAPI.close() : setQuick(false)} /></Suspense>}
        {!quick && <><a href="#main-workspace" className="skip-link">Skip to workspace</a>
        <header className="titlebar"><div className="brand"><span className="brand-symbol">i</span><span>INARA<span className="brand-sub">PERSONAL INTELLIGENCE</span></span></div>
            <div className="titlebar-center"><span className={`status-dot ${connected ? '' : 'offline'}`} />{connected ? 'SYSTEM ONLINE' : 'CONNECTING'}<span className="title-divider" /> COMMAND DECK</div>
            <div className="window-actions"><button aria-label="Minimize window" onClick={() => window.electronAPI?.minimize()}><Minus size={16} /></button>
                <button aria-label="Maximize window" onClick={() => window.electronAPI?.maximize()}><Maximize2 size={14} /></button>
                <button aria-label="Close to tray" title="Close workspace; INARA stays in the tray" onClick={() => window.electronAPI?.close()}><X size={18} /></button></div></header>
        <div className="deck-layout"><aside className="navigation"><div className="nav-caption">WORKSPACE</div>
            <nav aria-label="Main navigation">{[['assistant', LayoutDashboard, 'Command'], ['studio', Layers3, 'Studio'], ['devices', Cpu, 'Connections'], ['activity', History, 'Activity']].map(([key, Icon, label]) => <button key={key} className={page === key ? 'selected' : ''} aria-label={label} title={label} aria-current={page === key ? 'page' : undefined} onClick={() => setPage(key)}><Icon size={19} /><span>{label}</span>{page === key && <span className="nav-active-mark" />}</button>)}</nav>
            <div className="nav-project"><span className="eyebrow">CURRENT PROJECT</span><span><Box size={16} />{currentProject || 'temp'}</span><small>Context kept across sessions</small></div>
            <div className="nav-bottom"><button aria-label="Gaming mode" title="Gaming mode" onClick={toggleGaming} className={gaming ? 'gaming-selected' : ''} aria-pressed={gaming}><Gamepad2 size={19} /><span>Gaming mode</span><span className="toggle-switch" /></button>
                <button aria-label="Preferences" title="Preferences" onClick={() => openFeature('settings')}><Settings2 size={19} /><span>Preferences</span></button>
                {window.electronAPI && <button className="quit-button" aria-label="Quit INARA" onClick={() => window.electronAPI.quit()}><Power size={18} /><span>Quit INARA</span></button>}
                <div className="resident-note"><span className="status-dot" />{window.electronAPI ? 'Always within reach' : 'Browser preview'}<small>{resident.hotkeyReady ? 'CTRL + SHIFT + SPACE' : window.electronAPI ? 'REOPEN FROM SYSTEM TRAY' : 'DESKTOP MODE IN ELECTRON'}</small></div></div>
        </aside>
        <main id="main-workspace" className="workspace" tabIndex={-1}>
            <div className="workspace-top"><span className="breadcrumb">WORKSPACE <ChevronRight size={12} /><strong>{page === 'assistant' ? 'Command' : page === 'studio' ? 'Studio' : page === 'activity' ? 'Activity' : 'Connections'}</strong></span><button className="command-trigger" aria-label="Open command palette" onClick={() => setCommands(true)}><Search size={15} /><span>Find a tool</span><kbd>Ctrl K</kbd></button><Clock /></div>
            {resident.error && <div role="alert" className="system-banner">{resident.error}</div>}
            {gaming && <div className="system-banner gaming-banner"><Gamepad2 size={16} /> Gaming mode active. Creative tools and camera are paused; text and reminders remain available.</div>}
            {page === 'activity' ? <Suspense fallback={<PanelState kind="loading" title="Preparing your activity" />}><ActivityCenter gaming={gaming} onOpen={(feature, requestId) => openFeature(feature, undefined, requestId)} /></Suspense> : page === 'assistant' ? <>
                <section className="hero"><div className="hero-copy"><div className="eyebrow"><span className="tiny-line" /> A MIND FOR YOUR EVERYDAY</div>
                    <h1>Ready when<br /><span>you are.</span></h1><p>From the smallest task to your next big idea.<br className="desktop-break" /> Let’s make room for what matters.</p>
                    <div className="hero-actions"><button className="primary-button" onClick={() => setPage('studio')}>Explore Studio <ArrowUpRight size={16} /></button>
                        <button className="voice-button" disabled={!connected} onClick={() => setQuick(true)}><AudioLines size={17} />Quick assistant</button></div></div>
                    <CoreOrb active={processing || aiConnected} quiet={gaming} /></section>
                <div className="assistant-grid"><Conversation /><aside className="context-column">
                    <section className="surface system-card"><div className="section-heading"><span className="eyebrow">SYSTEM PULSE</span><Zap size={15} /></div>
                        <div className="pulse-status"><span className={`status-dot ${connected ? '' : 'offline'}`} /><strong>{connected ? 'At your service' : 'Waiting for connection'}</strong></div>
                        <button className="text-button" onClick={() => openFeature('capabilities')}>Capability center / diagnostics <ChevronRight size={14} /></button><div className="system-row"><span>Resource mode</span><strong>{gaming ? 'Gaming' : resource.state === 'studio' ? 'Studio' : 'Lightweight'}</strong></div>
                        <div className="system-row"><span>Voice</span><strong>{aiConnected ? 'Active' : 'Off'}</strong></div>
                        <div className="system-row"><span>Workspace memory</span><strong>{memory === null ? '—' : `${Math.round(memory)} MB`}</strong></div>
                        <div className="pulse-footer"><ShieldCheck size={13} /><span>Actions stay under your control</span></div></section>
                    <section className="surface reminders-card"><div className="section-heading"><span className="eyebrow">ON YOUR RADAR</span><Bell size={16} /></div>
                        <h2>{pending.length ? `${pending.length} upcoming` : 'A clear horizon'}<span className="heading-dot">.</span></h2>
                        {pending.length ? pending.slice(0, 3).map(r => <div className="radar-reminder" key={r.id}><span className="radar-dot" /><div><strong>{r.task}</strong><span>{new Date(r.trigger_at * 1000).toLocaleString([], {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                      })}</span></div></div>) : <p>Nothing scheduled right now.<br />More space for your next idea.</p>}
                        <button className="text-button" onClick={() => openFeature('reminder')}>Open reminders <ArrowUpRight size={15} /></button></section>
                </aside></div>
                <div className="quick-launch"><span className="eyebrow">A LITTLE MORE POSSIBLE</span><button onClick={() => openFeature('cad')} disabled={gaming}><Box size={17} />3D studio<ArrowUpRight size={14} /></button>
                    <button onClick={() => openFeature('camera')} disabled={gaming}><Camera size={17} />Vision studio<ArrowUpRight size={14} /></button><button onClick={() => openFeature('usage')}><Gauge size={17} />Usage &amp; quality<ArrowUpRight size={14} /></button><button onClick={() => openFeature('memory')}><BookOpen size={17} />Project memory<ArrowUpRight size={14} /></button><button onClick={() => openFeature('desktop')}><Cpu size={17} />Desktop tools<ArrowUpRight size={14} /></button></div>
            </> : <>
                <section className="page-intro"><span className="eyebrow">{page === 'studio' ? 'IDEAS, GIVEN FORM' : 'YOUR WORLD, CONNECTED'}</span><h1>{page === 'studio' ? <>Make something<br /><span>extraordinary.</span></> : <>A command center<br /><span>for your world.</span></>}</h1>
                    <p>{page === 'studio' ? 'Bring a little imagination. We’ll bring the workspace. Heavy tools load only when you open them.' : 'Your devices and daily tools, one deliberate action at a time.'}</p></section>
                <div className="feature-grid">{page === 'studio' ? <>
                    <FeatureCard icon={Box} title="3D studio" description="Build a parametric solid, explore it in 3D and export STL or GLB. Works offline." tag="LOCAL + ON DEMAND" disabled={gaming} onClick={() => openFeature('cad')} />
                    <FeatureCard icon={Camera} title="Vision studio" description="A live perspective, when you choose. Camera access starts only with your permission." tag="CAMERA OFF" disabled={gaming} onClick={() => openFeature('camera')} />
                    <FeatureCard icon={Globe2} title="Web inspector" description="Read public page text and discover links in a quiet, read-only workspace." tag="NO CLOUD INFERENCE" onClick={() => openFeature('browser')} />
                    <FeatureCard icon={Sparkles} title="Image atelier" description="Shape your next visual with prompts, seeds and protected revisions. Local models load only on demand." tag="MODEL SETUP LATER" disabled={gaming} onClick={() => openFeature('image')} />
                </> : <>
                    <FeatureCard icon={Smartphone} title="Android companion" description="Pair a device with your permission. Read laptop status and previews; tool-free chat has its own grant." tag="OPT-IN / SECURE LINK" onClick={() => openFeature('phone')} />
                    <FeatureCard icon={Bell} title="Reminders" description="A reliable nudge. Schedules and unfinished alerts survive restart." tag="LOCAL" onClick={() => openFeature('reminder')} />
                    <FeatureCard icon={Cpu} title="Desktop controls" description="Apps and selected system tools, with permission at every step." tag="ON DEMAND" onClick={() => openFeature('desktop')} />
                    <FeatureCard icon={Zap} title="Smart home" description="Connect your supported lights and devices when you’re ready." tag="SETUP REQUIRED" onClick={() => openFeature('kasa')} />
                    <FeatureCard icon={Box} title="Print workshop" description="Inspect your printers and prepare the next physical creation." tag="SETUP REQUIRED" onClick={() => openFeature('printer')} />
                </>}</div><div className="future-note"><Layers3 size={18} /><span>Offline scenes are ready. Image models and Android pairing can be configured separately. Your existing SIM and WhatsApp number stay yours.</span></div>
            </>}
            <footer className="workspace-footer"><span>INARA <span className="footer-separator">/</span> YOUR PERSONAL INTELLIGENCE</span><span><span className="status-dot" /> {connected ? 'CORE CONNECTED' : 'CORE OFFLINE'}</span></footer>
        </main></div>
        {activeFeature && <FeatureDialog key={activeFeature} feature={activeFeature} onClose={closeFeature} />}
        </>}
        {commands && !quick && !locked && <Suspense fallback={null}><CommandPalette onClose={closeCommands} onSelect={feature => feature === 'activity' ? setPage('activity') : openFeature(feature)} gaming={gaming} /></Suspense>}
        <ReminderAlert /><ConfirmationPopup />{locked && <Suspense fallback={null}><AuthLock /></Suspense>}
    </div>;
}
