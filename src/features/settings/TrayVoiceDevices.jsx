import React, { useCallback, useEffect, useMemo, useState } from 'react';
import socket from '../../services/socket';
import { createAudioDevicesClient, devicePatch } from '../../transport/audioDevicesClient.ts';
import { rpcFailureMessage } from './aiSettingsModel';
import {
  DEVICE_KINDS, TRAY_VOICE_HELP, deviceNote, deviceOptions, savedDevice, selectedValue, selectionFor,
} from './trayVoiceDevicesModel';

const ROW = 'flex flex-col gap-2 rounded-md border border-line bg-raised px-3 py-2';
const HELP = 'text-[0.75rem] leading-relaxed text-ink-2';
const SELECT = 'w-full rounded-md border border-line-strong bg-panel px-2 py-1.5 text-sm text-ink-1';

/**
 * Tray voice microphone and speaker, from the core's device list. `voice` is the saved
 * settings.voice; `patch(settings)` saves through update_settings and resolves to '' or a
 * failure message.
 */
export default function TrayVoiceDevices({ voice, patch }) {
  const client = useMemo(() => createAudioDevicesClient(socket), []);
  const [report, setReport] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [failure, setFailure] = useState('');

  useEffect(() => () => client.dispose(), [client]);
  const load = useCallback(() => {
    client.list().then((next) => { setReport(next); setLoadError(''); })
      .catch((error) => setLoadError(rpcFailureMessage(error)));
  }, [client]);
  useEffect(() => {
    load();
    return client.on('connect', load);
  }, [client, load]);

  const available = report?.available === true;
  const choose = async (kind, list, value) => {
    const entries = report?.[list] || [];
    const next = selectionFor(entries, savedDevice(voice, kind), value);
    if (next === null) return;
    setFailure(await patch(devicePatch(kind, next)));
  };

  return <div className={ROW} data-tray-voice-devices>
    <span className="text-sm text-ink-1">Tray voice devices</span>
    <p className={HELP}>{TRAY_VOICE_HELP}</p>
    {report && !available && <p className={HELP} role="status" data-devices-unavailable>{report.message}</p>}
    {DEVICE_KINDS.map(({ kind, label, list }) => {
      const entries = report?.[list] || [];
      const saved = savedDevice(voice, kind);
      const note = deviceNote(entries, saved, kind, available);
      return <div key={kind} className="flex flex-col gap-1">
        <label htmlFor={`tray-voice-${kind}`} className="text-[0.75rem] text-ink-2">{label}</label>
        <select id={`tray-voice-${kind}`} className={SELECT} disabled={!available}
          value={selectedValue(entries, saved)} onChange={(event) => choose(kind, list, event.target.value)}>
          {deviceOptions(entries, saved).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        {note && <p className={HELP} data-device-note={kind}>{note}</p>}
      </div>;
    })}
    <p aria-live="polite" className="min-h-0 text-[0.75rem] leading-snug text-danger">{loadError || failure}</p>
  </div>;
}
