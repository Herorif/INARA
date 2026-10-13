import { useEffect, useRef, useState } from 'react';
import { Camera, CameraOff, ScanLine } from 'lucide-react';
import useStore from '../../store';
import { createCapture } from './capture';
export default function CameraPanel() {
  const video = useRef(null),
    canvas = useRef(null),
    capture = useRef(null),
    tracker = useRef(null);
  const [phase, setPhase] = useState('idle'),
    [tracking, setTracking] = useState(false),
    [trackStatus, setTrackStatus] = useState('Off');
  useEffect(() => {
    capture.current = createCapture({
      acquire: () => navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          width: {
            ideal: 640
          },
          height: {
            ideal: 480
          },
          frameRate: {
            ideal: 15,
            max: 30
          },
          ...(useStore.getState().selectedWebcamId ? {
            deviceId: {
              exact: useStore.getState().selectedWebcamId
            }
          } : {})
        }
      }),
      attach: stream => {
        if (video.current) {
          video.current.srcObject = stream;
          if (stream) video.current.play().catch(() => {});
        }
      },
      status: setPhase
    });
    return () => {
      capture.current.stop();
    };
  }, []);
  useEffect(() => {
    if (!tracking || phase !== 'active') return;
    let cancelled = false,
      interval,
      activeTracker;
    setTrackStatus('Loading local landmarks…');
    import('./tracker').then(module => module.createTracker()).then(instance => {
      if (cancelled) {
        instance.close();
        return;
      }
      tracker.current = activeTracker = instance;
      setTrackStatus('Local · up to 10 FPS');
      let lastFrame = -1;
      interval = setInterval(() => {
        if (!video.current || video.current.readyState < 2 || video.current.currentTime === lastFrame) return;
        lastFrame = video.current.currentTime;
        try {
          const result = instance.detectForVideo(video.current, performance.now());
          const context = canvas.current?.getContext('2d');
          if (!context) return;
          context.clearRect(0, 0, 640, 480);
          context.fillStyle = '#8deaf1';
          for (const hand of result.landmarks) for (const point of hand) {
            context.beginPath();
            context.arc(point.x * 640, point.y * 480, 3, 0, Math.PI * 2);
            context.fill();
          }
        } catch {
          clearInterval(interval);
          setTrackStatus('Tracking unavailable. Disable and retry.');
        }
      }, 100);
    }).catch(error => {
      console.warn('Tracking initialization:', error.message);
      if (!cancelled) setTrackStatus('Local tracking could not load.');
    });
    return () => {
      cancelled = true;
      clearInterval(interval);
      activeTracker?.close();
      tracker.current = null;
      canvas.current?.getContext('2d')?.clearRect(0, 0, 640, 480);
    };
  }, [tracking, phase]);
  return <div className="camera-panel"><div className="camera-preview">
        <video ref={video} muted playsInline /><canvas ref={canvas} width={640} height={480} />
        {phase !== 'active' && <div className="camera-empty"><Camera size={36} /><h3>Your camera, on your terms.</h3><p>{phase === 'failed' ? 'Camera access was denied or unavailable. Check device permissions and try again.' : 'Start a local preview when you’re ready. No frames are sent to the assistant.'}</p></div>}
        <span className="camera-label"><span className={`status-dot ${phase === 'active' ? '' : 'offline'}`} />{phase === 'active' ? 'LOCAL PREVIEW' : 'CAMERA OFF'}</span></div>
        <div className="camera-controls"><button className="primary-button" disabled={phase === 'requesting'} onClick={() => {
        if (phase === 'active') {
          setTracking(false);
          capture.current.stop();
        } else capture.current.start();
      }}>{phase === 'active' ? <CameraOff size={16} /> : <Camera size={16} />} {phase === 'requesting' ? 'Waiting for permission…' : phase === 'active' ? 'Stop camera' : 'Start camera'}</button>
            <button className="voice-button" disabled={phase !== 'active'} aria-pressed={tracking} onClick={() => setTracking(!tracking)}><ScanLine size={18} />{tracking ? 'Disable landmarks' : 'Enable hand landmarks'}</button></div>
        <div className="camera-details"><span>FRAME SHARING <strong>Off</strong></span><span>HAND LANDMARKS <strong>{tracking ? trackStatus : 'Off'}</strong></span></div>
    </div>;
}
