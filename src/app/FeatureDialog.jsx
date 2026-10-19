import React, { lazy, Suspense, useRef } from 'react';
import PanelHeader from './PanelHeader';
import PanelState from './PanelState';
import { labels } from './features';
import { useDialogFocus } from './useDialogFocus';
import useStore from '../store';
const panels = {
  capabilities: lazy(() => import('./CapabilityCenter')),
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
  const connected = useStore(state => state.backendConnected);
  const dialog = useRef(null);
  const Panel = panels[feature];
  useDialogFocus(dialog, onClose);
  if (!Panel) return null;
  return <div className="dialog-backdrop" onMouseDown={event => {
    if (event.target === event.currentTarget) onClose();
  }}>
        <section ref={dialog} className={`feature-dialog ${feature === 'cad' ? 'cad-dialog' : feature === 'image' ? 'image-dialog' : ''}`} role="dialog" aria-modal="true" aria-labelledby="feature-title" tabIndex={-1}>
            <PanelHeader title={labels[feature]} onClose={onClose} />
            {!connected && !['camera','cad','image'].includes(feature) && <PanelState compact kind="offline" title="Core offline" detail="Reconnect before using assistant actions. Offline clicks are not queued for later." />}
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
