import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { AudioLines, Cable, Gamepad2, History, Inbox, Layers3, ListChecks, Maximize2, MessageSquare, Minus, PanelRight, Power, Search, Settings2, X } from 'lucide-react';
import useStore from '../store';
import socket, { emitSocket } from '../services/socket';
import FeatureDialog from './FeatureDialog';
import FeatureWorkspace from './FeatureWorkspace';
import Conversation from './Conversation';
import WorkspaceOverview from './WorkspaceOverview';
import WorkspaceInspector from './WorkspaceInspector';
import WorkspaceTray from './WorkspaceTray';
import ReminderAlert from '../components/ReminderAlert';
import ConfirmationPopup from '../components/ConfirmationPopup';
import PanelState from './PanelState';
import StatusChip from '../shared/ui/StatusChip';
import HudLabel from '../shared/ui/HudLabel';
import Kbd from '../shared/ui/Kbd';
import { UI_CONTRACT_VERSION } from '../transport/generated/version.ts';
import { flags, heavyFeatures } from './features';
import { voiceChip } from '../features/voice/status.js';
import { clearedFeatures, dialogFeatures, featureWorkspace, workspaceTitles } from './workspaceNavigation';
import './workspace.css';

const CommandPalette = lazy(() => import('./CommandPalette'));
const QuickAssistant = lazy(() => import('./QuickAssistant'));
const ActivityCenter = lazy(() => import('./ActivityCenter'));
const InboxWorkspace = lazy(() => import('./InboxWorkspace'));
const AuthLock = lazy(() => import('../components/AuthLock'));
const navigation = [['assistant', MessageSquare, 'Assistant'], ['studio', Layers3, 'Studio'], ['inbox', Inbox, 'Inbox'], ['tasks', ListChecks, 'Tasks'], ['connections', Cable, 'Connections']];

const datePart = (date, part) => new Intl.DateTimeFormat(undefined, { [part]: part === 'day' ? 'numeric' : 'short' }).format(date).replace(/\.$/, '');

function Clock() {
  const [time, setTime] = useState(new Date());
  useEffect(() => {
    let timer = 0;
    // Tick on the minute boundary so the displayed minute is never stale.
    const schedule = () => { timer = setTimeout(() => { setTime(new Date()); schedule(); }, 60000 - (Date.now() % 60000) + 50); };
    schedule();
    return () => clearTimeout(timer);
  }, []);
  const clock = time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  return <time className="deck-clock" dateTime={time.toISOString()}>
    <span className="deck-clock__time">{clock}</span>
    <HudLabel className="deck-clock__date">{`${datePart(time, 'weekday')} ${datePart(time, 'day')} ${datePart(time, 'month')}`}</HudLabel>
  </time>;
}

function CoreChip({ connected }) {
  return connected
    ? <StatusChip tone="ok" className="core-chip" title="Core online"><span className="chip-text">CORE ONLINE</span></StatusChip>
    : <StatusChip tone="danger" className="core-chip" title="Core offline"><span className="chip-text">CORE OFFLINE</span></StatusChip>;
}

function VoiceChip({ connected, gaming, voice }) {
  const label = voiceChip({ connected, gaming, voice });
  const tone = { OFF: 'idle', READY: 'ok', LISTENING: 'accent', SPEAKING: 'accent' }[label];
  return <StatusChip tone={tone} className="voice-chip" data-voice={label.toLowerCase()}>{`VOICE ${label}`}</StatusChip>;
}

export default function CommandDeck() {
  const quick = useStore(state => state.showQuickAssistant);
  const connected = useStore(state => state.backendConnected);
  const processing = useStore(state => state.textProcessing);
  const voice = useStore(state => state.voice);
  const currentProject = useStore(state => state.currentProject);
  const locked = useStore(state => state.isLockScreenVisible);
  const activeFlag = useStore(state => Object.keys(flags).find(key => !dialogFeatures.has(key) && state[flags[key]]) || null);
  const activeDialog = useStore(state => Object.keys(flags).find(key => dialogFeatures.has(key) && state[flags[key]]) || null);
  const [page, setPage] = useState('assistant');
  const [camera, setCamera] = useState(false);
  const [commands, setCommands] = useState(false);
  const [inspector, setInspector] = useState(() => window.matchMedia('(min-width: 1200px)').matches);
  const [tray, setTray] = useState(false);
  const [visible, setVisible] = useState(!document.hidden);
  const [resident, setResident] = useState({ phase:'browser',visible:true,gaming:false });
  const [memory, setMemory] = useState(null);
  const [resource, setResource] = useState({ state:'chat' });
  const canvas = useRef(null);
  const gaming = resident.gaming || resource.state === 'gaming';
  const activeFeature = camera ? 'camera' : activeFlag;
  const section = page === 'activity' ? 'studio' : page;
  const closeCommands = useCallback(() => setCommands(false), []);
  const closeDialog = useCallback(() => useStore.setState(clearedFeatures('dialog')), []);
  const closeFeature = useCallback(() => { setCamera(false); useStore.setState(clearedFeatures('workspace')); }, []);
  const setQuick = useCallback(value => {
    if (value && useStore.getState().isLockScreenVisible) return;
    if (value) { setCamera(false); setCommands(false); useStore.setState(clearedFeatures()); }
    useStore.setState({ showQuickAssistant:value });
    window.electronAPI?.setQuickMode?.(value);
  }, []);
  useEffect(() => window.electronAPI?.onQuickAssistant?.(setQuick), [setQuick]);
  useEffect(() => {
    let live = true;
    const api = window.electronAPI;
    api?.residentStatus?.().then(value => { if (live && value) setResident(value); }).catch(() => {});
    const cleanup = api?.onResidentState?.(setResident);
    const resourceUpdate = value => setResource(value);
    socket.on('resource_state', resourceUpdate);
    const metrics = async () => {
      if (document.hidden) return;
      try { const value = await api?.metrics?.(); if (live && value) setMemory(value.electronMemoryMB); } catch { if (live) setMemory(null); }
    };
    const visibility = () => { setVisible(!document.hidden); if (!document.hidden) metrics(); };
    document.addEventListener('visibilitychange', visibility);
    const media = window.matchMedia('(min-width: 1200px)');
    const resize = event => { if (!event.matches) setInspector(false); };
    media.addEventListener('change', resize);
    metrics();
    const timer = setInterval(metrics, 10000);
    return () => { live = false; cleanup?.(); clearInterval(timer); socket.off('resource_state', resourceUpdate); document.removeEventListener('visibilitychange', visibility); media.removeEventListener('change', resize); };
  }, []);
  useEffect(() => {
    if (locked) { closeFeature(); closeDialog(); setCommands(false); setQuick(false); useStore.setState({studioHandoff:null}); }
    else if (gaming && activeFeature && heavyFeatures.has(activeFeature)) closeFeature();
  }, [locked, gaming, activeFeature, closeFeature, closeDialog, setQuick]);
  useEffect(() => { if (activeFeature) { setPage(featureWorkspace(activeFeature)); setInspector(false); } }, [activeFeature]);

  const navigate = useCallback(next => {
    if (locked) return;
    closeDialog();
    if (next !== page || next === 'activity') closeFeature();
    setPage(next);
    if (next === 'tasks') useStore.setState({ ...clearedFeatures('workspace'), [flags.tasks]:true });
    canvas.current?.scrollTo({ top:0 });
  }, [locked, page, closeDialog, closeFeature]);
  const openFeature = useCallback((feature, heavy = heavyFeatures.has(feature), requestId = null) => {
    if (locked || (gaming && heavy)) return;
    if (feature === 'quick') { setQuick(true); return; }
    if (feature === 'activity' || feature === 'inbox') { navigate(feature); return; }
    if (!flags[feature] && feature !== 'camera') return;
    if (dialogFeatures.has(feature)) {
      useStore.setState({ ...clearedFeatures('dialog'), [flags[feature]]:true });
    } else {
      closeDialog();
      // Re-selecting the current tool leaves its draft/session mounted.
      if (feature !== activeFeature) {
        setCamera(feature === 'camera');
        useStore.setState({ ...clearedFeatures('workspace'), ...(flags[feature] ? { [flags[feature]]:true } : {}) });
      }
      useStore.setState({ studioSelection:requestId ? { feature, requestId, project:currentProject } : null });
      setPage(featureWorkspace(feature)); setInspector(false);
      if (heavy) emitSocket('set_resource_state', { state:'studio' });
    }
    if (feature === 'reminder') emitSocket('get_reminders');
    if (feature === 'settings' && navigator.mediaDevices) navigator.mediaDevices.enumerateDevices().then(devices => useStore.setState({
      micDevices:devices.filter(device => device.kind === 'audioinput'), speakerDevices:devices.filter(device => device.kind === 'audiooutput'), webcamDevices:devices.filter(device => device.kind === 'videoinput')
    })).catch(() => {});
  }, [locked, gaming, activeFeature, currentProject, closeDialog, navigate, setQuick]);
  const toggleGaming = async () => {
    const value = !gaming;
    try { await window.electronAPI?.setGaming(value); }
    catch { setResident(previous => ({ ...previous,error:'Gaming mode could not change. Check the core connection and retry.' })); return; }
    setResident(previous => ({ ...previous,gaming:value,error:null }));
    emitSocket('set_resource_state', { state:value ? 'gaming' : 'chat' });
  };
  useEffect(() => {
    const key = event => {
      if (locked || useStore.getState().confirmationRequest) return;
      if (event.ctrlKey && event.shiftKey && event.code === 'Space') { event.preventDefault(); setQuick(true); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !activeDialog && !quick) { event.preventDefault(); setCommands(value => !value); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [locked, activeDialog, quick, setQuick]);
  const [title, description] = workspaceTitles[page];
  return <div className={`command-deck ${gaming ? 'gaming-mode' : ''} ${quick ? 'quick-mode' : ''}`} data-resource-state={resource.state} data-ui-contract-version={UI_CONTRACT_VERSION} data-ui-visible={visible && resident.visible !== false}>
    {quick && !locked && <Suspense fallback={<PanelState kind="loading" title="Preparing quick assistant"/>}><QuickAssistant gaming={gaming} onExpand={() => setQuick(false)} onClose={() => window.electronAPI ? window.electronAPI.close() : setQuick(false)}/></Suspense>}
    {!quick && !locked && <><a href="#main-workspace" className="skip-link">Skip to workspace</a>
      <header className="titlebar">
        <div className="titlebar-brand brand"><span className="monogram brand-mark" aria-hidden="true">I</span><span className="brand-word">INARA</span></div>
        <div className="titlebar-main">
          <button type="button" className="command-trigger btn btn--secondary" aria-label="Open command palette" onClick={() => setCommands(true)}><Search size={14} aria-hidden="true"/><span className="command-trigger__text">Find a tool or action</span><Kbd>Ctrl K</Kbd></button>
        </div>
        <div className="titlebar-status">
          <div className="titlebar-chips"><CoreChip connected={connected}/><VoiceChip connected={connected} gaming={gaming} voice={voice}/></div>
          <Clock/>
          <div className="titlebar-actions">
            <button type="button" className="btn btn--ghost btn--icon" aria-label="Open quick assistant" title="Quick assistant" onClick={() => setQuick(true)}><AudioLines size={16} aria-hidden="true"/></button>
            <button type="button" className="btn btn--ghost btn--icon inspector-toggle" aria-label="Toggle context inspector" title="Context inspector" aria-expanded={inspector} aria-controls="workspace-inspector" onClick={() => setInspector(value => !value)}><PanelRight size={16} aria-hidden="true"/></button>
          </div>
          <span className="titlebar-divider" aria-hidden="true"/>
          <div className="window-actions">
            <button type="button" className="btn btn--ghost" aria-label="Minimize window" onClick={() => window.electronAPI?.minimize()}><Minus size={16} aria-hidden="true"/></button>
            <button type="button" className="btn btn--ghost" aria-label="Maximize window" onClick={() => window.electronAPI?.maximize()}><Maximize2 size={14} aria-hidden="true"/></button>
            <button type="button" className="btn btn--ghost window-close" aria-label="Close to tray" title="Close workspace; INARA stays in the tray" onClick={() => window.electronAPI?.close()}><X size={16} aria-hidden="true"/></button>
          </div>
        </div>
      </header>
      <div className="deck-layout"><aside className="navigation"><HudLabel className="nav-caption">WORKSPACE</HudLabel><nav aria-label="Main navigation">{navigation.map(([key, Icon, label]) => <button type="button" key={key} className={section === key ? 'selected' : ''} aria-label={label} title={label} aria-current={section === key ? 'page' : undefined} onClick={() => navigate(key)}><Icon size={16} aria-hidden="true"/><span>{label}</span></button>)}</nav>
        <div className="nav-project"><HudLabel>PROJECT</HudLabel><strong className="nav-project__name">{currentProject || 'temp'}</strong><button type="button" className="btn btn--ghost btn--sm nav-project__link" onClick={() => openFeature('memory')}>Project memory</button></div>
        <div className="nav-bottom"><button type="button" aria-label="Gaming mode" title="Gaming mode" onClick={toggleGaming} className={gaming ? 'gaming-selected' : ''} aria-pressed={gaming}><Gamepad2 size={16} aria-hidden="true"/><span>Gaming mode</span><span className="toggle-switch" aria-hidden="true"/></button><button type="button" aria-label="Preferences" title="Preferences" onClick={() => openFeature('settings')}><Settings2 size={16} aria-hidden="true"/><span>Preferences</span></button>{window.electronAPI && <button type="button" className="quit-button" aria-label="Quit INARA" onClick={() => window.electronAPI.quit()}><Power size={16} aria-hidden="true"/><span>Quit INARA</span></button>}<div className="resident-note"><HudLabel>QUICK ASSISTANT</HudLabel><Kbd>Ctrl Shift Space</Kbd></div></div>
      </aside>
      <main id="main-workspace" className="workspace" tabIndex={-1} data-page={page}>
        {resident.error && <div role="alert" className="system-banner">{resident.error}</div>}{gaming && <div className="system-banner gaming-banner"><Gamepad2 size={16} aria-hidden="true"/><span>Gaming mode is on. Creative tools and camera are paused; text and reminders are available.</span></div>}
        <div className={`workspace-body ${inspector ? 'with-inspector' : ''}`}><div ref={canvas} className={`workspace-canvas ${activeFeature ? 'has-feature' : ''}`}>
          {!activeFeature && <div className="workspace-heading"><div className="workspace-heading__copy"><h1>{title}</h1>{description && <p>{description}</p>}</div>{page === 'assistant' && <HudLabel className="workspace-heading__meta">{`PROJECT · ${currentProject || 'temp'}`}</HudLabel>}</div>}
          {(page === 'studio' || page === 'activity') && <div className="studio-tabs hud-tabs" role="group" aria-label="Studio workspaces">{[['cad','3D studio'],['image','Images'],['camera','Vision'],['browser','Web'],['activity','Artifacts']].map(([key,label]) => { const selected = activeFeature === key || page === key; return <button type="button" key={key} className={`hud-tab ${selected ? 'is-active' : ''}`} aria-pressed={selected} disabled={gaming && heavyFeatures.has(key)} onClick={() => openFeature(key)}>{key === 'activity' && <History size={14} aria-hidden="true"/>}{label}</button>; })}</div>}
          {activeFeature ? <FeatureWorkspace key={activeFeature} feature={activeFeature} onClose={closeFeature} onOpen={openFeature}/> : page === 'assistant' ? <Conversation onOpen={openFeature}/> : page === 'inbox' ? <Suspense fallback={<PanelState kind="loading" title="Opening your inbox"/>}><InboxWorkspace embedded onOpen={openFeature}/></Suspense> : page === 'activity' ? <Suspense fallback={<PanelState kind="loading" title="Collecting your work"/>}><ActivityCenter gaming={gaming} onOpen={(feature, requestId) => openFeature(feature, undefined, requestId)}/></Suspense> : <WorkspaceOverview page={page} gaming={gaming} onOpen={openFeature}/>}
        </div>{inspector && <WorkspaceInspector connected={connected} processing={processing} voice={voice} gaming={gaming} resource={resource} memory={memory} onOpen={openFeature} onClose={() => setInspector(false)}/>}</div>
        <WorkspaceTray expanded={tray} onToggle={() => setTray(value => !value)} onOpen={openFeature} gaming={gaming}/>
      </main></div>{activeDialog && <FeatureDialog key={activeDialog} feature={activeDialog} onClose={closeDialog}/>}</>}
    {commands && !quick && !locked && <Suspense fallback={null}><CommandPalette onClose={closeCommands} onSelect={openFeature} gaming={gaming}/></Suspense>}
    <ReminderAlert/><ConfirmationPopup/>{locked && <Suspense fallback={null}><AuthLock/></Suspense>}
  </div>;
}
