import React, { useRef } from 'react';
import PanelHeader from './PanelHeader';
import FeatureContent, { featureHostClass, hasFeaturePanel } from './FeatureContent';
import { labels } from './features';
import { useDialogFocus } from './useDialogFocus';
export default function FeatureDialog({
  feature,
  onClose,
  onOpen
}) {
  const dialog = useRef(null);
  useDialogFocus(dialog, onClose);
  if (!hasFeaturePanel(feature)) return null;
  return <div className="dialog-backdrop" onMouseDown={event => {
    if (event.target === event.currentTarget) onClose();
  }}>
        <section ref={dialog} className={`feature-dialog ${featureHostClass(feature)}`} role="dialog" aria-modal="true" aria-labelledby="feature-title" tabIndex={-1}>
            <PanelHeader title={labels[feature]} onClose={onClose} />
            <FeatureContent feature={feature} onClose={onClose} onOpen={onOpen} />
        </section>
    </div>;
}
