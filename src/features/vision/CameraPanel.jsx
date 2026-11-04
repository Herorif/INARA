import { useEffect, useRef, useState } from 'react';
import { Camera, CameraOff, ScanLine, RefreshCw, FlipHorizontal2, Focus, Eye, Hand, Pause } from 'lucide-react';
import useStore from '../../store';
import { createVisionSession } from './session';
import { createTrackingWorker } from './trackingClient';
import { drawOverlay, validHands } from './overlay';
import Field from '../../app/Field';
import StatusChip from '../../shared/ui/StatusChip';
import EmptyState from '../../shared/ui/EmptyState';
import './vision.css';
const initial = {
  phase: 'idle',
  tracking: 'off',
  reason: '',
  error: ''
};
const captureErrors = {
  NotAllowedError: 'Camera permission was denied. Allow access in your device settings, then retry.',
  NotFoundError: 'No camera is available. Connect a camera and refresh sources.',
  NotReadableError: 'This camera is busy or unavailable. Close the other camera app and retry.',
  OverconstrainedError: 'This source cannot provide the requested preview. Choose another camera.'
};
const pauseReasons = {
  hidden: 'The workspace was hidden. Start the camera when you return.',
  minimized: 'The workspace was minimized. Start the camera when you return.',
  suspend: 'The computer went to sleep. Start a fresh camera session.',
  locked: 'The computer was locked. Start a fresh camera session.',
  playback: 'The preview could not play. Check the source and retry.',
  device: 'The active source disappeared. Choose a camera and start again.'
};
export default function CameraPanel() {
  const video = useRef(null),
    canvas = useRef(null),
    session = useRef(null),
    alive = useRef(false),
    overlayRef = useRef('skeleton'),
    lastResult = useRef(null),
    lastUI = useRef(0),
    activeDevice = useRef(''),
    deviceEpoch = useRef(0);
  const [state, setState] = useState(initial),
    [devices, setDevices] = useState([]),
    [source, setSource] = useState(useStore.getState().selectedWebcamId || ''),
    [mirrored, setMirrored] = useState(true),
    [overlay, setOverlay] = useState('skeleton'),
    [rate, setRate] = useState(10),
    [signal, setSignal] = useState(null),
    [observation, setObservation] = useState(null),
    [sourceError, setSourceError] = useState('');
  overlayRef.current = overlay;
  const refreshDevices = async () => {
    const generation = ++deviceEpoch.current;
    try {
      const result = await navigator.mediaDevices.enumerateDevices();
      if (!alive.current || generation !== deviceEpoch.current) return;
      const cameras = result.filter(device => device.kind === 'videoinput');
      setDevices(cameras);
      setSourceError('');
      if (session.current?.snapshot().phase === 'active' && activeDevice.current && !cameras.some(device => device.deviceId === activeDevice.current)) session.current.stop('device');
    } catch {
      if (alive.current && generation === deviceEpoch.current) setSourceError('Camera sources could not be listed. You can still try the default source.');
    }
  };
  useEffect(() => {
    alive.current = true;
    const clear = () => {
      lastResult.current = null;
      canvas.current?.getContext('2d')?.clearRect(0, 0, canvas.current.width, canvas.current.height);
      if (alive.current) setObservation(null);
    };
    session.current = createVisionSession({
      acquire: constraints => navigator.mediaDevices.getUserMedia(constraints),
      attach: stream => {
        if (!video.current) return;
        video.current.srcObject = stream;
        if (stream) {
          const track = stream.getVideoTracks()[0],
            settings = track?.getSettings() || {};
          activeDevice.current = settings.deviceId || '';
          if (alive.current) setSignal({
            width: settings.width,
            height: settings.height,
            label: track?.label || 'Local camera'
          });
          video.current.play().catch(() => {
            if (alive.current && video.current?.srcObject === stream) session.current.stop('playback');
          });
          refreshDevices();
        } else {
          video.current.pause();
          activeDevice.current = '';
          if (alive.current) setSignal(null);
        }
      },
      frameSource: () => {
        const element = video.current;
        if (!element || element.readyState < 2 || !element.videoWidth || element.paused) return null;
        const scale = Math.min(640 / element.videoWidth, 480 / element.videoHeight, 1);
        return {
          time: element.currentTime,
          capture: () => createImageBitmap(element, {
            resizeWidth: Math.max(1, Math.round(element.videoWidth * scale)),
            resizeHeight: Math.max(1, Math.round(element.videoHeight * scale))
          })
        };
      },
      makeTracker: createTrackingWorker,
      onState: next => {
        if (alive.current) setState(next);
      },
      onClear: clear,
      onResult: result => {
        lastResult.current = result;
        drawOverlay(canvas.current, result, {
          width: video.current?.videoWidth || 640,
          height: video.current?.videoHeight || 480,
          mode: overlayRef.current
        });
        if (alive.current && performance.now() - lastUI.current >= 250) {
          lastUI.current = performance.now();
          setObservation({
            hands: validHands(result).length,
            inferenceMs: result.inferenceMs,
            sides: (result.handedness || []).slice(0, 2).map(categories => categories[0]).filter(Boolean)
          });
        }
      }
    });
    const visibility = () => {
      if (document.hidden) session.current.stop('hidden');
    };
    const leave = () => session.current.stop('hidden');
    const offPause = window.electronAPI?.onCapturePause?.(reason => session.current.stop(reason));
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', leave);
    navigator.mediaDevices?.addEventListener?.('devicechange', refreshDevices);
    refreshDevices();
    return () => {
      alive.current = false;
      // eslint-disable-next-line react-hooks/exhaustive-deps -- a request counter, not a DOM ref: bumping its live value invalidates in-flight replies
      deviceEpoch.current++;
      session.current.dispose();
      offPause?.();
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('pagehide', leave);
      navigator.mediaDevices?.removeEventListener?.('devicechange', refreshDevices);
    };
  }, []);
  useEffect(() => {
    drawOverlay(canvas.current, lastResult.current, {
      width: video.current?.videoWidth || 640,
      height: video.current?.videoHeight || 480,
      mode: overlay
    });
  }, [overlay]);
  const active = state.phase === 'active',
    requesting = state.phase === 'requesting',
    tracking = ['loading', 'running'].includes(state.tracking);
  const status = requesting ? 'Waiting for permission' : active ? state.tracking === 'running' ? 'Tracking hands locally' : 'Local preview active' : state.phase === 'paused' ? 'Session paused' : state.phase === 'lost' ? 'Camera disconnected' : state.phase === 'failed' ? 'Camera unavailable' : 'Camera off';
  const [tone, chip] = active ? ['accent', 'Live'] : requesting ? ['warn', 'Waiting'] : state.phase === 'paused' ? ['warn', 'Paused'] : ['lost', 'failed'].includes(state.phase) ? ['danger', 'Error'] : ['idle', 'Off'];
  const explanation = state.phase === 'failed' ? captureErrors[state.error] || 'The camera could not start. Check its connection and permissions, then retry.' : state.phase === 'lost' ? 'Your camera disconnected. Refresh the sources and start a fresh session.' : state.phase === 'paused' ? pauseReasons[state.reason] || 'Start the camera to begin a fresh session.' : requesting ? 'Allow camera access in the device prompt. Cancel here to discard any late permission result.' : 'Camera access starts only when you start it.';
  return <div className="vision-studio camera-panel" data-capture-phase={state.phase} data-tracking-phase={state.tracking}>
    <div className="vision-intro"><div><h3>Camera preview</h3><p>Local camera and hand landmarks. Frames stay on this device.</p></div><StatusChip className="vision-live" tone={tone}>{chip}</StatusChip></div>
    <div className="vision-layout"><section className="vision-workbench" aria-label="Camera preview and tracking">
      <div className="vision-section-title"><span className="hud-label">Preview</span><span className="hud-label">{mirrored ? 'Mirrored' : 'Natural'} / {active ? 'Live' : 'Standby'}</span></div>
      <div className={`vision-preview camera-preview ${active ? 'active' : ''}`}>
        <div className={`vision-feed ${mirrored ? 'mirrored' : ''}`}><video ref={video} muted playsInline /><canvas ref={canvas} width={640} height={480} aria-label="Local hand landmark overlay" /></div>
        {!active && <EmptyState className="vision-empty camera-empty" icon={state.phase === 'paused' ? <Pause strokeWidth={1.5} /> : <Focus strokeWidth={1.5} />} title={status} body={explanation} />}
        <div className="vision-view-label hud-label"><span className={`status-dot ${active ? 'status-dot--accent' : ''}`} aria-hidden="true" />{active ? 'Local preview' : 'Camera off'}</div>
        {active && <div className="vision-preview-bottom"><span>{signal?.label || 'Local camera'}</span><span>{signal?.width && signal?.height ? `${signal.width} × ${signal.height}` : 'Detecting signal'}</span></div>}
      </div>
      <div className="vision-status" role="status"><StatusChip tone={tone}>{chip}</StatusChip><div><strong>{status}</strong><span>{active ? 'Frames stay in this workspace. Recording and action control are off.' : explanation}</span></div></div>
      <div className="vision-telemetry camera-details hud-panel"><div><span className="hud-label">Hand presence</span><strong>{observation ? `${observation.hands} / 2 detected` : state.tracking === 'running' ? 'Waiting for fresh frames' : '—'}</strong></div><div><span className="hud-label">Inference</span><strong>{observation && Number.isFinite(observation.inferenceMs) ? `${observation.inferenceMs.toFixed(0)} ms` : '—'}</strong></div><div><span className="hud-label">Frame sharing</span><strong>Off / local only</strong></div></div>
    </section><aside className="vision-controls"><div className="vision-section-title"><span className="hud-label">Session</span></div>
      <Field className="vision-field" label="Camera source"><div className="vision-source"><select aria-label="Camera source" disabled={requesting} value={source} onChange={event => {
              const next = event.target.value;
              setSource(next);
              useStore.setState({
                selectedWebcamId: next
              });
              if (active) session.current.start(next);
            }}><option value="">Default camera</option>{source && !devices.some(device => device.deviceId === source) && <option value={source}>Previous camera / unavailable</option>}{devices.map((device, index) => <option value={device.deviceId} key={device.deviceId || index}>{device.label || `Camera ${index + 1}`}</option>)}</select><button type="button" className="btn btn--secondary btn--icon" aria-label="Refresh camera sources" title="Refresh camera sources" onClick={refreshDevices}><RefreshCw size={15} aria-hidden="true" /></button></div></Field>
      {sourceError && <p className="vision-warning" role="status">{sourceError}</p>}
      <div className="vision-session-buttons camera-controls"><button type="button" className="primary-button btn btn--primary" onClick={() => active || requesting ? session.current.stop() : session.current.start(source)}>{active || requesting ? <CameraOff size={16} aria-hidden="true" /> : <Camera size={16} aria-hidden="true" />}{requesting ? 'Cancel camera request' : active ? 'Stop camera' : 'Start camera'}</button><button type="button" className="vision-toggle btn btn--secondary" aria-pressed={mirrored} onClick={() => setMirrored(value => !value)}><FlipHorizontal2 size={16} aria-hidden="true" />Mirror preview<span className="hud-label">{mirrored ? 'On' : 'Off'}</span></button></div>
      <div className="vision-tracking-card hud-panel"><div><Hand size={16} aria-hidden="true" /><strong>Hand landmarks</strong><span className="hud-label">Opt-in</span></div><p>Track up to two hands with the bundled local model. No gestures trigger actions.</p><button type="button" className="voice-button btn btn--secondary" disabled={!active || typeof Worker === 'undefined' || typeof createImageBitmap === 'undefined'} aria-pressed={tracking} onClick={() => session.current.track(!tracking, rate)}><ScanLine size={16} aria-hidden="true" />{state.tracking === 'loading' ? 'Cancel tracking load' : tracking ? 'Disable landmarks' : state.tracking === 'failed' ? 'Retry hand tracking' : 'Enable hand landmarks'}</button><div className="vision-tracking-status" role="status">{state.tracking === 'loading' ? 'Loading the local worker and model…' : state.tracking === 'running' ? `Worker active / up to ${rate} FPS` : state.tracking === 'failed' ? 'Tracking stopped. Retry to load a fresh worker.' : 'Off / model unloaded'}</div></div>
      <Field className="vision-field" label="Overlay"><select aria-label="Landmark overlay" value={overlay} onChange={event => setOverlay(event.target.value)}><option value="skeleton">Skeleton + points</option><option value="points">Points only</option><option value="off">Hide overlay</option></select></Field>
      <Field className="vision-field" label="Tracking budget"><select aria-label="Tracking rate" value={rate} onChange={event => {
            const next = Number(event.target.value);
            setRate(next);
            if (tracking) session.current.track(true, next);
          }}><option value={5}>Light / up to 5 FPS</option><option value={10}>Balanced / up to 10 FPS</option></select></Field>
      <div className="vision-hand-summary"><span className="hud-label">Side classification</span>{observation?.sides.length ? observation.sides.map((side, index) => <div key={index}><span className={`vision-hand-dot hand-${index}`} aria-hidden="true" /><strong>{side.categoryName} <small>(model)</small></strong><span>{Number.isFinite(side.score) ? `${Math.round(side.score * 100)}%` : '—'}</span></div>) : <p>{observation?.hands === 0 ? 'No hands in the latest frame.' : 'Enable tracking to inspect the latest hand classification.'}</p>}<small>Scores describe left/right classification, not identity or tracking accuracy. Mirroring changes the display only.</small></div>
    </aside></div><div className="vision-footer"><Eye size={15} aria-hidden="true" /><span>Camera and model stop when this panel closes, the workspace hides, the computer sleeps or gaming starts. Restart is always deliberate.</span></div>
  </div>;
}
