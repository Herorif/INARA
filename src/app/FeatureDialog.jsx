import React, { lazy, Suspense, useEffect, useRef } from 'react';
import PanelHeader from './PanelHeader';
import PanelState from './PanelState';
const panels = {
  image: lazy(() => import('../features/images/ImageStudio')),
  cad: lazy(() => import('../features/cad/CadStudio')),
  browser: lazy(() => import('../components/BrowserWindow')),
  kasa: lazy(() => import('../components/KasaWindow')),
  printer: lazy(() => import('../components/PrinterWindow')),
  phone: lazy(() => import('../components/PhoneWindow')),
  reminder: lazy(() => import('../features/reminders/ReminderPanel')),
  routines: lazy(() => import('../components/ReminderWindow')),
  desktop: lazy(() => import('../components/DesktopWindow')),
  vision: lazy(() => import('../components/VisionWindow')),
  device: lazy(() => import('../components/DeviceWindow')),
  settings: lazy(() => import('../components/SettingsWindow')),
  camera: lazy(() => import('../features/vision/CameraPanel'))
};
const labels = {
  cad: '3D studio',
  image: 'Image atelier',
  browser: 'Research browser',
  kasa: 'Smart home',
  printer: 'Print workshop',
  phone: 'Phone controls',
  reminder: 'Reminders',
  desktop: 'Desktop controls',
  vision: 'Scene watches',
  device: 'Connected devices',
  settings: 'Preferences',
  camera: 'Vision studio',
  routines: 'Routine manager'
};
class PanelBoundary extends React.Component {
  state = {
    failed: false
  };
  static getDerivedStateFromError() {
    return {
      failed: true
    };
  }
  render() {
    return this.state.failed ? <PanelState kind="error" title="Workspace interrupted" detail="Your saved work is preserved. Close and reopen this panel to try again." /> : this.props.children;
  }
}
export default function FeatureDialog({
  feature,
  onClose
}) {
  const dialog = useRef(null);
  const Panel = panels[feature];
  useEffect(() => {
    const previous = document.activeElement;
    dialog.current?.focus();
    const onKey = event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      }
      if (event.key === 'Tab') {
        const items = [...dialog.current.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]')].filter(el => el.getClientRects().length);
        const first = items[0],
          last = items.at(-1);
        if (!first) {
          event.preventDefault();
          return;
        }
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus();
    };
  }, [onClose]);
  if (!Panel) return null;
  return <div className="dialog-backdrop" onMouseDown={event => {
    if (event.target === event.currentTarget) onClose();
  }}>
        <section ref={dialog} className={`feature-dialog ${feature === 'cad' ? 'cad-dialog' : feature === 'image' ? 'image-dialog' : ''}`} role="dialog" aria-modal="true" aria-labelledby="feature-title" tabIndex={-1}>
            <PanelHeader title={labels[feature]} onClose={onClose} />
            <div className={`legacy-panel ${feature === 'camera' ? 'camera-host' : ''}`}>
                <PanelBoundary key={feature}><Suspense fallback={<PanelState kind="loading" title="Preparing your workspace" detail="Bringing the tools you need into focus." />}>
                    <Panel position={{
              x: 0,
              y: 0
            }} zIndex={1} onMouseDown={() => {}} onClose={onClose} />
                </Suspense></PanelBoundary>
            </div>
        </section>
    </div>;
}
