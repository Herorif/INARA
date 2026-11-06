import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import socket from '../../services/socket';
import { createAudioDevicesClient } from '../../transport/audioDevicesClient.ts';
import { rpcFailureMessage } from './aiSettingsModel';
import SegmentedControl from './SegmentedControl';
import Switch from './Switch';
import {
  WAKE_SENSITIVITIES, WAKE_SWITCH_LABEL, WAKE_WORD_HELP, WAKE_WORD_LABEL,
  sensitivityHelp, sensitivityPatch, wakeStatusText, wakeWordChoice, wakeWordPatch,
} from './wakeWordModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const LINE = 'flex flex-wrap items-center justify-between gap-x-3 gap-y-2';

/**
 * "Hey Jarvis" switch, sensitivity and status (J3c). `voice` is the saved settings.voice;
 * `patch(settings)` saves through update_settings and resolves to '' or a failure message.
 */
export default function WakeWordSettings({ voice, patch }) {
  const client = useMemo(() => createAudioDevicesClient(socket), []);
  const choice = wakeWordChoice(voice);
  const [status, setStatus] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [failure, setFailure] = useState('');
  const latest = useRef(0);

  useEffect(() => () => client.dispose(), [client]);
  // Only the newest answer counts when reads overlap.
  const load = useCallback(() => {
    const request = ++latest.current;
    client.wakeWordStatus().then((next) => {
      if (request === latest.current) { setStatus(next); setLoadError(''); }
    }).catch((error) => {
      if (request === latest.current) { setStatus(null); setLoadError(rpcFailureMessage(error)); }
    });
  }, [client]);
  useEffect(() => {
    load();
    return client.on('connect', load);
  }, [client, load]);

  const save = async (next) => {
    if (!next) return;
    const message = await patch(next);
    setFailure(message);
    if (!message) load();
  };
  const toggle = () => save(wakeWordPatch(choice, !choice.enabled));
  const statusText = wakeStatusText(status);

  return <div className={ROW} data-wake-word-settings>
    <div className={LINE}>
      <span id="wake-word-label" className="text-sm text-ink-1">{WAKE_WORD_LABEL}</span>
      <Switch checked={choice.enabled} label={WAKE_SWITCH_LABEL} onClick={toggle} />
    </div>
    <p className={HELP}>{WAKE_WORD_HELP}</p>
    {choice.enabled && <>
      <div className={LINE}>
        <span id="wake-sensitivity-label" className="text-[0.75rem] text-ink-2">Sensitivity</span>
        <SegmentedControl name="wake-sensitivity" options={WAKE_SENSITIVITIES} value={choice.sensitivity}
          onChange={(id) => save(sensitivityPatch(choice, id))} aria-labelledby="wake-sensitivity-label" />
      </div>
      <p className={HELP} data-wake-sensitivity-help>{sensitivityHelp(choice.sensitivity)}</p>
    </>}
    {statusText && <p className={HELP} role="status" aria-live="polite" data-wake-status>{statusText}</p>}
    <p aria-live="polite" className="min-h-0 text-[0.75rem] leading-snug text-danger">{loadError || failure}</p>
  </div>;
}
