import React, { useState } from 'react';
import Switch from './Switch';
import { OVERLAY_HELP, OVERLAY_LABEL, overlayChoice, overlayPatch } from './overlaySettingsModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const LINE = 'flex flex-wrap items-center justify-between gap-x-3 gap-y-2';

/**
 * "Show JARVIS while you talk" switch (J4c). `voice` is the saved settings.voice;
 * `patch(settings)` saves through update_settings and resolves to '' or a failure message.
 */
export default function OverlaySettings({ voice, patch }) {
  const choice = overlayChoice(voice);
  const [failure, setFailure] = useState('');

  const toggle = async () => {
    const next = overlayPatch(choice, !choice.enabled);
    if (!next) return;
    setFailure(await patch(next));
  };

  return <div className={ROW} data-overlay-settings>
    <div className={LINE}>
      <span id="overlay-label" className="text-sm text-ink-1">{OVERLAY_LABEL}</span>
      <Switch checked={choice.enabled} label={OVERLAY_LABEL} onClick={toggle} />
    </div>
    <p className={HELP}>{OVERLAY_HELP}</p>
    <p aria-live="polite" className="min-h-0 text-[0.75rem] leading-snug text-danger">{failure}</p>
  </div>;
}
