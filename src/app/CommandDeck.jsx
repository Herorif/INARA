import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Brain, Cable, DraftingCompass, Gamepad2, History, Inbox, Layers3, ListChecks, Maximize2, MessageSquare, Minus, PanelRight, PhoneCall, PictureInPicture2, Power, Search, Settings2, X } from 'lucide-react';
import useStore from '../store';
import socket, { emitSocket } from '../services/socket';
import FeatureDialog from './FeatureDialog';
import FeatureWorkspace from './FeatureWorkspace';
import AssistantView from './AssistantView';
import WorkspaceOverview from './WorkspaceOverview';
import WorkspaceInspector from './WorkspaceInspector';
import WorkspaceTray from './WorkspaceTray';
import ReminderAlert from '../components/ReminderAlert';
import VipCallAlert from '../features/calls/VipCallAlert';
import RememberedNotice from '../features/memory/RememberedNotice';
import ConfirmationPopup from '../components/ConfirmationPopup';
import PanelState from './PanelState';
import StatusChip from '../shared/ui/StatusChip';
import HudLabel from '../shared/ui/HudLabel';
import Kbd from '../shared/ui/Kbd';
import BrandMark from '../shared/ui/BrandMark';
import { UI_CONTRACT_VERSION } from '../transport/generated/version.ts';
import { flags, heavyFeatures } from './features';
import { voiceChip } from '../features/voice/status.js';
import { clearedFeatures, dialogFeatures, featureWorkspace, workspaceTitles } from './workspaceNavigation';
import useCallsStatus from '../features/calls/useCallsStatus';
import { startPresencePing } from '../features/calls/presence';
import { bannerVisible } from '../features/liveDesign/model.js';
import { useMotionMode } from '../shared/motion/materialise.js';
import { parallaxEnabled } from './glowModel.js';
import useGridParallax from './useGridParallax.js';
import useUiSoundContext from '../services/sound/useUiSoundContext.js';
import './workspace.css';

const CommandPalette = lazy(() => import('./CommandPalette'));
const QuickAssistant = lazy(() => import('./QuickAssistant'));
const ActivityCenter = lazy(() => import('./ActivityCenter'));
const InboxWorkspace = lazy(() => import('./InboxWorkspace'));
const CallsWorkspace = lazy(() => import('../features/calls/CallsWorkspace'));
const MemoryWorkspace = lazy(() => import('../features/memory/MemoryWorkspace'));
const AuthLock = lazy(() => import('../components/AuthLock'));
const navigation = [['assistant', MessageSquare, 'Assistant'], ['studio', Layers3, 'Studio'], ['inbox', Inbox, 'Inbox'], ['callsview', PhoneCall, 'Calls'], ['tasks', ListChecks, 'Tasks'], ['knows', Brain, 'Memory'], ['connections', Cable, 'Connections']];

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
  const liveDesign = useStore(state => state.liveDesign);
  const liveDesignSeen = useStore(state => state.liveDesignSeen);
  const liveDesignShown = useStore(state => state.liveDesignPanelVisible);
  const callsFocus = useStore(state => state.callsFocus);
  const reminderShown = useStore(state => !!state.activeAlert);
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
  const { status: calls } = useCallsStatus(connected && !locked);
  const needsYou = calls?.needs_you_count || 0;
  useUiSoundContext({ gaming, onCall: !!calls?.active_call });
  // Tells the core the owner is at the PC, so urgent briefings are not phoned in meanwhile.
  useEffect(() => (connected && !locked ? startPresencePing({ socket }) : undefined), [connected, locked]);
  const activeFeature = camera ? 'camera' : activeFlag;
  // The dot grid on the void sits behind the Assistant view only; its parallax needs full motion.
  const voidGrid = page === 'assistant' && !activeFeature;
  const motion = useMotionMode({ gaming });
  const parallax = voidGrid && parallaxEnabled(motion);
  useGridParallax(canvas, parallax);
  const section = page === 'activity' ? 'studio' : page;
  const closeCommands = useCallback(() => setCommands(false), []);
  const closeDialog = useCallback(() => useStore.setState(clearedFeatures('dialog')), []);
  const closeFeature = useCallback(() => { setCamera(false); useStore.setState(clearedFeatures('workspace')); }, []);
  // Shows or hides the quick assistant in this page only; false when the lock screen refuses it.
  const applyQuick = useCallback(value => {
    if (value && useStore.getState().isLockScreenVisible) return false;
    if (value) { setCamera(false); setCommands(false); useStore.setState(clearedFeatures()); }
    useStore.setState(value && !useStore.getState().showQuickAssistant ? { showQuickAssistant:value, quickOpenedAt:performance.now() } : { showQuickAssistant:value });
    return true;
  }, []);
  // A switch started here also resizes the window.
  const setQuick = useCallback(value => { if (applyQuick(value)) window.electronAPI?.setQuickMode?.(value); }, [applyQuick]);
  // The window already switched (tray hotkey): follow it, never echo it back. If the lock
  // screen refuses quick mode, ask the window to return to its full size.
  useEffect(() => window.electronAPI?.onQuickAssistant?.(value => {
    if (!applyQuick(value) && value) window.electronAPI?.setQuickMode?.(false);
  }), [applyQuick]);
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
  // S6.4: a fact's "from a conversation" link shows that conversation in the Assistant view.
  const openConversation = useCallback(id => { useStore.getState().adoptConversation?.(id); navigate('assistant'); }, [navigate]);
  // P1: a VIP alert's "Call back" or a VIP balloon click opens Calls on that record.
  useEffect(() => { if (callsFocus && !locked) { if (quick) setQuick(false); navigate('callsview'); } }, [callsFocus, locked]); // eslint-disable-line react-hooks/exhaustive-deps
  const openFeature = useCallback((feature, heavy = heavyFeatures.has(feature), requestId = null) => {
    if (locked || (gaming && heavy)) return;
    if (feature === 'quick') { setQuick(true); return; }
    if (feature === 'activity' || feature === 'inbox' || feature === 'callsview' || feature === 'knows') { navigate(feature); return; }
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
      speakerDevices:devices.filter(device => device.kind === 'audiooutput'), webcamDevices:devices.filter(device => device.kind === 'videoinput')
    })).catch(() => {});
  }, [locked, gaming, activeFeature, currentProject, closeDialog, navigate, setQuick]);
  // V2 Show JARVIS: the core asked this workspace for one photo (look_through_camera); open the Vision studio.
  const visionFocus = useStore(state => state.visionFocus);
  useEffect(() => { if (visionFocus && !locked && !gaming) { if (quick) setQuick(false); openFeature('camera'); useStore.setState({ visionFocus:null }); } }, [visionFocus, locked, gaming]); // eslint-disable-line react-hooks/exhaustive-deps
  // W1 World view: the core pushed a view (world_view) and no World page shows it; open one.
  const worldFocus = useStore(state => state.worldFocus);
  useEffect(() => { if (worldFocus && !locked && !gaming) { if (quick) setQuick(false); openFeature('world'); useStore.setState({ worldFocus:null }); } }, [worldFocus, locked, gaming]); // eslint-disable-line react-hooks/exhaustive-deps
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
  // JARVIS added steps to the live design while the owner is on another page or in a feature.
  const designBanner = (page !== 'assistant' || !!activeFeature) && bannerVisible({ design: liveDesign, seen: liveDesignSeen, panelVisible: liveDesignShown });
  return <div className={`command-deck ${gaming ? 'gaming-mode' : ''} ${quick ? 'quick-mode' : ''}`} data-resource-state={resource.state} data-ui-contract-version={UI_CONTRACT_VERSION} data-ui-visible={visible && resident.visible !== false}>
    {quick && !locked && <Suspense fallback={<PanelState kind="loading" title="Preparing quick assistant"/>}><QuickAssistant gaming={gaming} onExpand={() => setQuick(false)} onClose={() => window.electronAPI ? window.electronAPI.close() : setQuick(false)}/></Suspense>}
    {!quick && !locked && <><a href="#main-workspace" className="skip-link">Skip to workspace</a>
      <header className="titlebar">
        <div className="titlebar-brand brand"><BrandMark size={24} /><span className="brand-word">JARVIS</span></div>
        <div className="titlebar-main">
          <button type="button" className="command-trigger btn btn--secondary" aria-label="Open command palette" onClick={() => setCommands(true)}><Search size={14} aria-hidden="true"/><span className="command-trigger__text">Find a tool or action</span><Kbd>Ctrl K</Kbd></button>
        </div>
        <div className="titlebar-status">
          <div className="titlebar-chips"><CoreChip connected={connected}/>{calls?.active_call && <button type="button" className="on-call-chip" aria-label="On a call. Open Calls" title="JARVIS is on a call" onClick={() => navigate('callsview')}><StatusChip tone="accent"><span className="chip-text">ON CALL</span></StatusChip></button>}<VoiceChip connected={connected} gaming={gaming} voice={voice}/></div>
          <Clock/>
          <div className="titlebar-actions">
            <button type="button" className="btn btn--secondary btn--sm titlebar-quick" aria-label="Open quick assistant" title="Shrink to the quick assistant (Ctrl+Shift+Space)" onClick={() => setQuick(true)}><PictureInPicture2 size={16} aria-hidden="true"/><span className="titlebar-quick__text">Quick assistant</span></button>
            <button type="button" className="btn btn--ghost btn--icon inspector-toggle" aria-label="Toggle context inspector" title="Context inspector" aria-expanded={inspector} aria-controls="workspace-inspector" onClick={() => setInspector(value => !value)}><PanelRight size={16} aria-hidden="true"/></button>
          </div>
          <span className="titlebar-divider" aria-hidden="true"/>
          <div className="window-actions">
            <button type="button" className="btn btn--ghost" aria-label="Minimize window" onClick={() => window.electronAPI?.minimize()}><Minus size={16} aria-hidden="true"/></button>
            <button type="button" className="btn btn--ghost" aria-label="Maximize window" onClick={() => window.electronAPI?.maximize()}><Maximize2 size={14} aria-hidden="true"/></button>
            <button type="button" className="btn btn--ghost window-close" aria-label="Close to tray" title="Close workspace; JARVIS stays in the tray" onClick={() => window.electronAPI?.close()}><X size={16} aria-hidden="true"/></button>
          </div>
        </div>
      </header>
      <div className="deck-layout"><aside className="navigation"><HudLabel className="nav-caption">WORKSPACE</HudLabel><nav aria-label="Main navigation">{navigation.map(([key, Icon, label]) => <button type="button" key={key} className={section === key ? 'selected' : ''} aria-label={label} title={label} aria-current={section === key ? 'page' : undefined} aria-describedby={key === 'callsview' && needsYou ? 'nav-calls-count' : undefined} onClick={() => navigate(key)}><Icon size={16} aria-hidden="true"/><span>{label}</span>{key === 'callsview' && needsYou > 0 && <span className="nav-badge" aria-hidden="true">{needsYou > 99 ? '99+' : needsYou}</span>}</button>)}</nav>{needsYou > 0 && <span id="nav-calls-count" className="sr-only">{`${needsYou} ${needsYou === 1 ? 'call needs' : 'calls need'} you`}</span>}
        <div className="nav-project"><HudLabel>PROJECT</HudLabel><strong className="nav-project__name">{currentProject || 'temp'}</strong><button type="button" className="btn btn--ghost btn--sm nav-project__link" onClick={() => openFeature('memory')}>Project memory</button></div>
        <div className="nav-bottom"><button type="button" className="nav-quick" aria-label="Quick assistant" aria-keyshortcuts="Control+Shift+Space" title="Quick assistant (Ctrl+Shift+Space)" onClick={() => setQuick(true)}><PictureInPicture2 size={16} aria-hidden="true"/><span>Quick assistant</span></button><button type="button" aria-label="Gaming mode" title="Gaming mode" onClick={toggleGaming} className={gaming ? 'gaming-selected' : ''} aria-pressed={gaming}><Gamepad2 size={16} aria-hidden="true"/><span>Gaming mode</span><span className="toggle-switch" aria-hidden="true"/></button><button type="button" aria-label="Preferences" title="Preferences" onClick={() => openFeature('settings')}><Settings2 size={16} aria-hidden="true"/><span>Preferences</span></button>{window.electronAPI && <button type="button" className="quit-button" aria-label="Quit JARVIS" onClick={() => window.electronAPI.quit()}><Power size={16} aria-hidden="true"/><span>Quit JARVIS</span></button>}</div>
      </aside>
      <main id="main-workspace" className="workspace" tabIndex={-1} data-page={page}>
        {resident.error && <div role="alert" className="system-banner">{resident.error}</div>}{designBanner && <div role="status" className="system-banner system-banner--accent live-design-banner"><DraftingCompass size={16} aria-hidden="true"/><span>{`JARVIS is designing “${liveDesign.name}”.`}</span><button type="button" className="btn btn--secondary btn--sm system-banner__action" onClick={() => navigate('assistant')}>Open live design</button></div>}<RememberedNotice/>{gaming && <div className="system-banner gaming-banner"><Gamepad2 size={16} aria-hidden="true"/><span>Gaming mode is on. Creative tools and camera are paused; text and reminders are available.</span></div>}
        <div className={`workspace-body ${inspector ? 'with-inspector' : ''}`}><div ref={canvas} className={`workspace-canvas ${activeFeature ? 'has-feature' : ''} ${voidGrid ? 'workspace-canvas--void' : ''}`} data-parallax={voidGrid ? (parallax ? 'on' : 'off') : undefined}>
          {!activeFeature && page !== 'callsview' && page !== 'knows' && <div className="workspace-heading"><div className="workspace-heading__copy"><h1>{title}</h1>{description && <p>{description}</p>}</div>{page === 'assistant' && <HudLabel className="workspace-heading__meta">{`PROJECT · ${currentProject || 'temp'}`}</HudLabel>}</div>}
          {(page === 'studio' || page === 'activity') && <div className="studio-tabs hud-tabs" role="group" aria-label="Studio workspaces">{[['cad','3D studio'],['image','Images'],['camera','Vision'],['browser','Web'],['world','World'],['activity','Artifacts']].map(([key,label]) => { const selected = activeFeature === key || page === key; return <button type="button" key={key} className={`hud-tab ${selected ? 'is-active' : ''}`} aria-pressed={selected} disabled={gaming && heavyFeatures.has(key)} onClick={() => openFeature(key)}>{key === 'activity' && <History size={14} aria-hidden="true"/>}{label}</button>; })}</div>}
          {activeFeature ? <FeatureWorkspace key={activeFeature} feature={activeFeature} onClose={closeFeature} onOpen={openFeature}/> : page === 'assistant' ? <AssistantView onOpen={openFeature} gaming={gaming}/> : page === 'inbox' ? <Suspense fallback={<PanelState kind="loading" title="Opening your inbox"/>}><InboxWorkspace embedded onOpen={openFeature}/></Suspense> : page === 'callsview' ? <Suspense fallback={<PanelState kind="loading" title="Opening calls"/>}><CallsWorkspace/></Suspense> : page === 'knows' ? <Suspense fallback={<PanelState kind="loading" title="Opening what JARVIS knows"/>}><MemoryWorkspace onOpenConversation={openConversation}/></Suspense> : page === 'activity' ? <Suspense fallback={<PanelState kind="loading" title="Collecting your work"/>}><ActivityCenter gaming={gaming} onOpen={(feature, requestId) => openFeature(feature, undefined, requestId)}/></Suspense> : <WorkspaceOverview page={page} gaming={gaming} onOpen={openFeature}/>}
        </div>{inspector && <WorkspaceInspector connected={connected} processing={processing} voice={voice} gaming={gaming} resource={resource} memory={memory} showPresence={!(page === 'assistant' && !activeFeature)} onOpen={openFeature} onClose={() => setInspector(false)}/>}</div>
        <WorkspaceTray expanded={tray} onToggle={() => setTray(value => !value)} onOpen={openFeature} gaming={gaming}/>
      </main></div>{activeDialog && <FeatureDialog key={activeDialog} feature={activeDialog} onClose={closeDialog}/>}</>}
    {commands && !quick && !locked && <Suspense fallback={null}><CommandPalette onClose={closeCommands} onSelect={openFeature} gaming={gaming}/></Suspense>}
    <ReminderAlert/><VipCallAlert stacked={reminderShown}/><ConfirmationPopup/>{locked && <Suspense fallback={null}><AuthLock/></Suspense>}
  </div>;
}
