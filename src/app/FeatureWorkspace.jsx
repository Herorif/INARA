import React, { useEffect, useRef } from 'react';
import FeatureContent, { featureHostClass, hasFeaturePanel } from './FeatureContent';
import PanelHeader from './PanelHeader';
import { labels } from './features';
import './feature-workspace.css';

/** Persistent shell surface; navigation remains reachable while a tool is open. */
export default function FeatureWorkspace({ feature, onClose, onOpen }) {
  const workspace = useRef(null);
  const opener = useRef(document.activeElement);
  useEffect(() => {
    workspace.current?.focus({ preventScroll: true });
  }, [feature]);

  const closeWorkspace = () => {
    onClose();
    // Restore only after an explicit close. Navigation/unmount has its own
    // focus destination, and a separate modal keeps ownership of its focus.
    requestAnimationFrame(() => {
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      const visible = element => element instanceof HTMLElement &&
        element !== document.body && element !== document.documentElement &&
        element.isConnected && !element.matches(':disabled') &&
        !element.closest('[inert], [aria-hidden="true"]') &&
        element.getClientRects().length > 0 &&
        getComputedStyle(element).visibility !== 'hidden';
      const previous = opener.current;
      const target = visible(previous)
        ? previous
        : document.querySelector('nav[aria-label="Main navigation"] button[aria-current="page"]');
      if (visible(target)) target.focus({ preventScroll: true });
    });
  };

  if (!hasFeaturePanel(feature)) return null;
  return <section
    ref={workspace}
    className={`feature-dialog feature-workspace ${featureHostClass(feature)}`}
    role="region"
    aria-labelledby="workspace-feature-title"
    tabIndex={-1}
  >
    <PanelHeader title={labels[feature]} titleId="workspace-feature-title" onClose={closeWorkspace} />
    <FeatureContent feature={feature} onClose={closeWorkspace} onOpen={onOpen} />
  </section>;
}
