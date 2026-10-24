import React, { lazy, Suspense } from 'react';
import useStore from '../store';
import PanelState from './PanelState';

// Both hosts share this registry. A workspace owns only its active panel, so
// closing or switching it releases the panel's subscriptions and resources.
const panels = {
  calls: lazy(() => import('./CallLab')),
  connections: lazy(() => import('./ConnectionReadiness')),
  tasks: lazy(() => import('./TaskQueue')),
  usage: lazy(() => import('./UsageCenter')),
  memory: lazy(() => import('./ProjectMemory')),
  capabilities: lazy(() => import('./CapabilityCenter')),
  image: lazy(() => import('../features/images/ImageStudio')),
  cad: lazy(() => import('../features/cad/CadStudio')),
  browser: lazy(() => import('../components/BrowserWindow')),
  kasa: lazy(() => import('../components/KasaWindow')),
  printer: lazy(() => import('../components/PrinterWindow')),
  phone: lazy(() => import('./MobileCompanion')),
  reminder: lazy(() => import('../features/reminders/ReminderPanel')),
  routines: lazy(() => import('../components/ReminderWindow')),
  desktop: lazy(() => import('../components/DesktopWindow')),
  vision: lazy(() => import('../components/VisionWindow')),
  device: lazy(() => import('../components/DeviceWindow')),
  settings: lazy(() => import('../components/SettingsWindow')),
  camera: lazy(() => import('../features/vision/CameraPanel')),
};

export const hasFeaturePanel = feature => Object.hasOwn(panels, feature);
export const featureHostClass = feature =>
  feature === 'cad' ? 'cad-dialog' : feature === 'image' ? 'image-dialog' : '';

class PanelBoundary extends React.Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed
      ? <PanelState kind="error" title="Workspace interrupted" detail="Your saved work is preserved. Close and reopen this panel to try again." />
      : this.props.children;
  }
}

export default function FeatureContent({ feature, onClose, onOpen }) {
  const connected = useStore(state => state.backendConnected);
  const Panel = panels[feature];
  if (!Panel) return null;

  return <>
    {!connected && !['camera', 'cad', 'image'].includes(feature) &&
      <PanelState compact kind="offline" title="Core offline" detail="Reconnect before using assistant actions. Offline clicks are not queued for later." />}
    <div className={`legacy-panel ${feature === 'camera' ? 'camera-host' : ''}`}>
      <PanelBoundary key={feature}>
        <Suspense fallback={<PanelState kind="loading" title="Preparing your workspace" detail="Bringing the tools you need into focus." />}>
          <Panel position={{ x: 0, y: 0 }} zIndex={1} onMouseDown={() => {}} onClose={onClose} onOpen={onOpen} />
        </Suspense>
      </PanelBoundary>
    </div>
  </>;
}
