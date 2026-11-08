import { useEffect, useRef, useState } from 'react';
import { Aperture, Camera, CameraOff, ScanLine, RefreshCw, FlipHorizontal2, Focus, Eye, Hand, Pause } from 'lucide-react';
import useStore from '../../store';
import socket from '../../services/socket';
import { createVisionSession } from './session';
import { captureStill, blobToBase64 } from './still';
import { askAboutPhoto } from './showJarvisClient';
import { EXPOSURE_MS, QUESTION_LIMIT, answerQuestion, askFollowUp, canSend, cancelFollowUp, captureFailure, discardPhoto, editQuestion, expirePhoto, failQuestion, hasPhoto, initialShow, photoExpiresIn, sendQuestion, streamAnswer, takeStill } from './showJarvisModel';
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
const PHOTO_NOTE = 'One photo, sent only to your AI provider for this question. It isn’t saved.';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const frameReady = element => !!element && element.readyState >= 2 && element.videoWidth > 0 && !element.paused;
export default function CameraPanel() {
  const video = useRef(null),
    canvas = useRef(null),
    session = useRef(null),
    alive = useRef(false),
    overlayRef = useRef('skeleton'),
    lastResult = useRef(null),
    lastUI = useRef(0),
    activeDevice = useRef(''),
    deviceEpoch = useRef(0),
    photo = useRef(null),
    showRef = useRef(initialShow),
    sourceRef = useRef(''),
    capturing = useRef(null),
    handledJob = useRef(null),
    shooting = useRef(false),
    showButton = useRef(null),
    questionField = useRef(null);
  const [state, setState] = useState(initial),
    [devices, setDevices] = useState([]),
    [source, setSource] = useState(useStore.getState().selectedWebcamId || ''),
    [mirrored, setMirrored] = useState(true),
    [overlay, setOverlay] = useState('skeleton'),
    [rate, setRate] = useState(10),
    [signal, setSignal] = useState(null),
    [observation, setObservation] = useState(null),
    [sourceError, setSourceError] = useState(''),
    [show, setShow] = useState(initialShow),
    [stillUrl, setStillUrl] = useState(null),
    [stillError, setStillError] = useState(''),
    [busyShot, setBusyShot] = useState(false);
  const connected = useStore(store => store.backendConnected),
    replying = useStore(store => store.textProcessing || store.conversationRestoring),
    captureJob = useStore(store => store.visionCapture),
    sendingId = show.phase === 'sending' ? show.turns.at(-1)?.requestId || null : null,
    streamed = useStore(store => (sendingId ? store.messages.find(message => message.requestKey === sendingId)?.text ?? null : null));
  overlayRef.current = overlay;
  showRef.current = show;
  sourceRef.current = source;
  // The photo's bytes and preview URL live in this ref only, never in state, the store or a file.
  const dropPhoto = () => {
    if (photo.current?.url) URL.revokeObjectURL(photo.current.url);
    photo.current = null;
    if (alive.current) setStillUrl(null);
  };
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
      if (photo.current?.url) URL.revokeObjectURL(photo.current.url);
      photo.current = null;
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
  // The answer streams into the chat; the card shows the same text as it arrives.
  useEffect(() => {
    if (sendingId && typeof streamed === 'string') setShow(value => streamAnswer(value, { requestId: sendingId, text: streamed }));
  }, [sendingId, streamed]);
  // The photo is dropped after five minutes, and its bytes go whenever the photo does.
  useEffect(() => {
    if (!show.photo || show.phase === 'sending') return undefined;
    const timer = setTimeout(() => setShow(value => expirePhoto(value, Date.now())), photoExpiresIn(show, Date.now()) + 50);
    return () => clearTimeout(timer);
  }, [show]);
  useEffect(() => {
    if (!show.photo) dropPhoto();
  }, [show.photo]); // dropPhoto only touches refs and the URL state
  // Voice (look_through_camera, approved by the owner): start the camera, wait about a second
  // for exposure, take one frame, stop the camera and hand the frame back once.
  useEffect(() => {
    if (!captureJob || handledJob.current === captureJob.requestId) return undefined;
    handledJob.current = captureJob.requestId;
    const job = captureJob, own = session.current;
    if (hasPhoto(showRef.current) || shooting.current || capturing.current) {
      job.settle({ error: 'busy' });
      return undefined;
    }
    let cancelled = false;
    capturing.current = job;
    const finish = result => {
      if (cancelled) return;
      if (capturing.current === job) capturing.current = null;
      job.settle(result);
    };
    const current = () => own.snapshot();
    const release = () => {
      if (['active', 'requesting'].includes(current().phase)) own.stop();
    };
    (async () => {
      try {
        await own.start(sourceRef.current);
        if (cancelled) return;
        if (current().phase !== 'active') return finish({ error: captureFailure(current()) });
        for (let waited = 0; waited < 3000 && !cancelled && !frameReady(video.current) && current().phase === 'active'; waited += 100) await sleep(100);
        await sleep(EXPOSURE_MS);
        if (cancelled) return;
        if (current().phase !== 'active' || !frameReady(video.current)) {
          const failure = current().phase === 'active' ? 'failed' : captureFailure(current());
          release();
          return finish({ error: failure });
        }
        const image = await blobToBase64(await captureStill(video.current));
        release();
        finish({ image });
      } catch {
        release();
        finish({ error: 'failed' });
      }
    })();
    return () => {
      if (!cancelled && capturing.current === job) {
        cancelled = true;
        capturing.current = null;
        // A remount (React's development check) takes the same job again; a real unmount
        // (panel closed, lock, gaming) answers it at once and the core tells the owner.
        handledJob.current = null;
        setTimeout(() => {
          if (!alive.current) job.settle({ error: useStore.getState().isLockScreenVisible ? 'locked' : 'failed' });
        }, 0);
      }
    };
  }, [captureJob]);
  const takePhoto = async () => {
    if (shooting.current || capturing.current || showRef.current.phase !== 'camera-on') return;
    shooting.current = true;
    setBusyShot(true);
    setStillError('');
    try {
      const blob = await captureStill(video.current);
      const base64 = await blobToBase64(blob);
      if (!alive.current) return;
      dropPhoto();
      const url = URL.createObjectURL(blob);
      photo.current = { base64, url };
      setStillUrl(url);
      setShow(value => takeStill(value, { id: crypto.randomUUID(), takenAt: Date.now() }));
      setTimeout(() => questionField.current?.focus(), 0);
    } catch {
      if (alive.current) setStillError('The photo couldn’t be taken. Check the preview and try again.');
    } finally {
      shooting.current = false;
      if (alive.current) setBusyShot(false);
    }
  };
  const sendPhoto = async () => {
    const current = showRef.current, requestId = crypto.randomUUID();
    const next = sendQuestion(current, { requestId, connected, busy: replying });
    if (next === current || !photo.current) return;
    setShow(next);
    const result = await askAboutPhoto({ socket, store: useStore, question: next.turns.at(-1).question, image: photo.current.base64, requestId });
    if (!alive.current) return;
    setShow(value => (result.ok ? answerQuestion(value, { requestId, text: result.text }) : failQuestion(value, { requestId, message: result.message })));
  };
  const leavePhoto = () => {
    setShow(value => discardPhoto(value));
    setTimeout(() => showButton.current?.focus(), 0);
  };
  const followUp = () => {
    setShow(value => askFollowUp(value));
    setTimeout(() => questionField.current?.focus(), 0);
  };
  const active = state.phase === 'active',
    requesting = state.phase === 'requesting',
    tracking = ['loading', 'running'].includes(state.tracking);
  const status = requesting ? 'Waiting for permission' : active ? state.tracking === 'running' ? 'Tracking hands locally' : 'Local preview active' : state.phase === 'paused' ? 'Session paused' : state.phase === 'lost' ? 'Camera disconnected' : state.phase === 'failed' ? 'Camera unavailable' : 'Camera off';
  // The camera indicator: on whenever a stream is live, manual or voice.
  const [tone, chip] = active ? ['warn', 'CAMERA ON'] : requesting ? ['warn', 'Waiting'] : state.phase === 'paused' ? ['warn', 'Paused'] : ['lost', 'failed'].includes(state.phase) ? ['danger', 'Error'] : ['idle', 'Off'];
  const showingStill = hasPhoto(show) && !!stillUrl,
    asking = show.phase === 'still' || show.phase === 'follow-up',
    sendable = canSend(show, { connected, busy: replying });
  const questionInput = <textarea ref={questionField} className="vision-ask-question" aria-label="Your question" placeholder="What would you like to know?" rows={3} maxLength={QUESTION_LIMIT} value={show.question} disabled={!asking} onChange={event => setShow(value => editQuestion(value, event.target.value))} onKeyDown={event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
        event.preventDefault();
        if (sendable) sendPhoto();
      }
    }} />;
  const explanation = state.phase === 'failed' ? captureErrors[state.error] || 'The camera could not start. Check its connection and permissions, then retry.' : state.phase === 'lost' ? 'Your camera disconnected. Refresh the sources and start a fresh session.' : state.phase === 'paused' ? pauseReasons[state.reason] || 'Start the camera to begin a fresh session.' : requesting ? 'Allow camera access in the device prompt. Cancel here to discard any late permission result.' : 'Camera access starts only when you start it.';
  return <div className="vision-studio camera-panel" data-capture-phase={state.phase} data-tracking-phase={state.tracking}>
    <div className="vision-intro"><div><h3>Camera preview</h3><p>Local camera and hand landmarks. The preview stays on this PC; Show JARVIS sends one photo only when you choose.</p></div><StatusChip className="vision-live" tone={tone}>{chip}</StatusChip></div>
    <div className="vision-layout"><section className="vision-workbench" aria-label="Camera preview and tracking">
      <div className="vision-section-title"><span className="hud-label">Preview</span><span className="hud-label">{mirrored ? 'Mirrored' : 'Natural'} / {active ? 'Live' : 'Standby'}</span></div>
      <div className={`vision-preview camera-preview ${active ? 'active' : ''} ${showingStill ? 'has-still' : ''}`}>
        <div className={`vision-feed ${mirrored ? 'mirrored' : ''}`}><video ref={video} muted playsInline /><canvas ref={canvas} width={640} height={480} aria-label="Local hand landmark overlay" /></div>
        {showingStill && <img className={`vision-still ${mirrored ? 'mirrored' : ''}`} src={stillUrl} alt="The still photo for JARVIS" />}
        {show.phase === 'still' && showingStill && <span className="vision-still-tag hud-label">Still photo · not sent yet</span>}
        {!active && !showingStill && <EmptyState className="vision-empty camera-empty" icon={state.phase === 'paused' ? <Pause strokeWidth={1.5} /> : <Focus strokeWidth={1.5} />} title={status} body={explanation} />}
        <div className="vision-view-label hud-label"><span className={`status-dot ${active ? 'status-dot--accent' : ''}`} aria-hidden="true" />{active ? 'Local preview' : 'Camera off'}</div>
        {active && !showingStill && <div className="vision-preview-bottom"><span>{signal?.label || 'Local camera'}</span><span>{signal?.width && signal?.height ? `${signal.width} × ${signal.height}` : 'Detecting signal'}</span></div>}
      </div>
      <div className="vision-status"><StatusChip tone={tone}>{chip}</StatusChip><div role="status"><strong>{status}</strong><span>{active ? 'The preview stays on this PC. Recording and action control are off.' : explanation}</span></div><button ref={showButton} type="button" className="btn btn--primary vision-show-jarvis" disabled={!active || show.phase !== 'camera-on' || busyShot || !!captureJob} onClick={takePhoto}><Aperture size={16} aria-hidden="true" />Show JARVIS</button></div>
      {stillError && <p className="vision-warning" role="alert">{stillError}</p>}
      <div className="vision-telemetry camera-details hud-panel"><div><span className="hud-label">Hand presence</span><strong>{observation ? `${observation.hands} / 2 detected` : state.tracking === 'running' ? 'Waiting for fresh frames' : '—'}</strong></div><div><span className="hud-label">Inference</span><strong>{observation && Number.isFinite(observation.inferenceMs) ? `${observation.inferenceMs.toFixed(0)} ms` : '—'}</strong></div><div><span className="hud-label">Frame sharing</span><strong>Only photos you send</strong></div></div>
    </section><aside className="vision-controls">{hasPhoto(show) && <section className="vision-ask-card hud-panel" aria-label={show.phase === 'still' ? undefined : 'Photo question'} aria-labelledby={show.phase === 'still' ? 'vision-ask-title' : undefined} data-phase={show.phase}>
        {show.phase === 'still' ? <>
          <h4 id="vision-ask-title" className="vision-ask-title">Send this photo to JARVIS?</h4>
          {questionInput}
          <p className="vision-ask-note">{PHOTO_NOTE}</p>
          {show.error && <p className="vision-ask-error" role="alert">{show.error}</p>}
          <div className="vision-ask-buttons"><button type="button" className="btn btn--primary" disabled={!sendable} onClick={sendPhoto}>Send to JARVIS</button><button type="button" className="btn btn--secondary" onClick={leavePhoto}>Retake</button><button type="button" className="btn btn--ghost" onClick={leavePhoto}>Cancel</button></div>
        </> : <>
          <ol className="vision-ask-turns">{show.turns.map(turn => <li key={turn.requestId} className="vision-ask-turn" data-status={turn.status}>
            <span className="hud-label">You · photo</span><p className="vision-ask-you">{turn.question}</p>
            <span className="hud-label vision-ask-jarvis-label">JARVIS</span><p className="vision-ask-answer" aria-live={turn.status === 'sending' ? 'polite' : undefined} aria-busy={turn.status === 'sending'}>{turn.answer || (turn.status === 'sending' ? '…' : '')}</p>
          </li>)}</ol>
          {show.phase === 'follow-up' ? <>
            {questionInput}
            {show.error && <p className="vision-ask-error" role="alert">{show.error}</p>}
            <div className="vision-ask-buttons"><button type="button" className="btn btn--primary" disabled={!sendable} onClick={sendPhoto}>Send to JARVIS</button><button type="button" className="btn btn--ghost" onClick={() => setShow(value => cancelFollowUp(value))}>Cancel</button></div>
          </> : <div className="vision-ask-buttons"><button type="button" className="btn btn--secondary" disabled={show.phase !== 'answered'} onClick={followUp}>Ask a follow-up</button><button type="button" className="btn btn--ghost" disabled={show.phase !== 'answered'} onClick={leavePhoto}>Take another</button></div>}
        </>}
      </section>}<div className="vision-section-title"><span className="hud-label">Session</span></div>
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
